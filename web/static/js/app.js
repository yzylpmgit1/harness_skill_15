/* ============================================
   HARNESS // 赛博朋克控制台前端逻辑
   ============================================
   功能模块：
   1. 时钟更新
   2. 声明性记忆管理（remember/forget/refresh/preview）
   3. 技能列表加载与展示
   4. 技能优化（进度条/对比报告/保存）
   5. 模态框管理
   ============================================ */

// ==================== 全局状态 ====================
let currentOptimizeData = null;  // 当前优化结果数据
let currentSkillName = null;     // 当前正在优化的技能名

// ==================== 可折叠模块 ====================

/**
 * 切换模块的展开/折叠状态
 * @param {string} moduleId - 模块 section 的 id
 */
function toggleModule(moduleId) {
    const section = document.getElementById(moduleId);
    if (!section) return;
    section.classList.toggle('collapsed');
}

// ==================== 工具函数 ====================

/**
 * 时钟更新 —— 每秒刷新顶部时钟
 */
function updateClock() {
    const now = new Date();
    const h = String(now.getHours()).padStart(2, '0');
    const m = String(now.getMinutes()).padStart(2, '0');
    const s = String(now.getSeconds()).padStart(2, '0');
    document.getElementById('clock').textContent = `${h}:${m}:${s}`;
}

/**
 * 显示 Toast 提示
 * @param {string} panel - 面板名 'memory' 或 'skill'
 * @param {string} message - 提示文本
 * @param {string} type - 类型：success / error / info
 */
function showToast(panel, message, type = 'info') {
    const toast = document.getElementById(`${panel}-toast`);
    if (!toast) return;
    toast.textContent = message;
    toast.className = `result-toast ${type}`;
    toast.style.display = 'block';

    // 3秒后自动隐藏
    setTimeout(() => {
        toast.style.display = 'none';
    }, 3000);
}

/**
 * 模拟进度条动画（用于 LLM 调用等耗时操作）
 * 进度从 0 递增到 90%，API 响应后跳到 100%
 *
 * @param {string} panel - 'memory' 或 'skill'
 * @param {string} label - 进度条标签
 * @param {Array} logMessages - 进度日志消息列表
 * @returns {Object} { complete, addLog } 控制对象
 */
function startProgress(panel, label, logMessages = []) {
    const area = document.getElementById(`${panel}-progress-area`);
    const bar = document.getElementById(`${panel}-progress-bar`);
    const percentEl = document.getElementById(`${panel}-progress-percent`);
    const labelEl = document.getElementById(`${panel}-progress-label`);
    const logEl = document.getElementById(`${panel}-progress-log`);

    // 重置状态
    bar.style.width = '0%';
    percentEl.textContent = '0%';
    labelEl.textContent = label;
    logEl.innerHTML = '';
    area.style.display = 'block';

    let progress = 0;
    let logIndex = 0;

    // 添加初始日志
    if (logMessages.length > 0) {
        addLogLine(logMessages[0]);
        logIndex = 1;
    }

    // 进度递增定时器
    const timer = setInterval(() => {
        // 越接近 90 越慢
        const increment = progress < 30 ? 5 : progress < 60 ? 3 : progress < 80 ? 1.5 : 0.5;
        progress = Math.min(progress + increment, 90);
        bar.style.width = progress + '%';
        percentEl.textContent = Math.round(progress) + '%';

        // 按进度添加日志
        const logThresholds = [20, 45, 70, 85];
        for (let i = 0; i < logThresholds.length; i++) {
            if (progress >= logThresholds[i] && logIndex <= i + 1 && logIndex < logMessages.length) {
                addLogLine(logMessages[logIndex]);
                logIndex++;
            }
        }
    }, 200);

    function addLogLine(msg) {
        const line = document.createElement('div');
        line.className = 'log-line';
        line.textContent = `> ${msg}`;
        logEl.appendChild(line);
        logEl.scrollTop = logEl.scrollHeight;
    }

    // 返回控制对象
    return {
        // 完成（API 返回后调用）
        complete(success = true, finalMsg = '完成') {
            clearInterval(timer);
            progress = 100;
            bar.style.width = '100%';
            percentEl.textContent = '100%';
            labelEl.textContent = success ? finalMsg : '执行失败';
            addLogLine(success ? `✓ ${finalMsg}` : `✗ 执行失败`);

            // 1.5秒后隐藏进度条
            setTimeout(() => {
                area.style.display = 'none';
            }, 1500);
        },
        // 添加自定义日志
        addLog(msg) {
            addLogLine(msg);
        }
    };
}

/**
 * 通用 API 调用封装
 *
 * 健壮性设计：
 * 1. 先读取响应文本，再尝试 JSON.parse，避免 response.json() 在非 JSON 响应时抛出
 *    不可控的 SyntaxError（如后端返回 HTML 500 错误页面时）
 * 2. 网络错误（fetch 本身失败）也会被 catch 并转换为友好的 Error
 */
async function apiCall(url, method = 'GET', body = null) {
    const options = {
        method,
        headers: { 'Content-Type': 'application/json' },
    };
    if (body) {
        options.body = JSON.stringify(body);
    }

    let response;
    try {
        response = await fetch(url, options);
    } catch (networkErr) {
        // fetch 本身失败（网络中断、服务器未启动等）
        throw new Error(`网络请求失败: ${networkErr.message}`);
    }

    // 先读取原始文本（body 只能读一次，所以先 text 再 parse）
    const text = await response.text();

    // 尝试解析为 JSON
    let data;
    try {
        data = JSON.parse(text);
    } catch (parseErr) {
        // 响应不是 JSON（可能是 Flask 返回的 HTML 错误页面）
        throw new Error(`服务器返回了非 JSON 响应 (HTTP ${response.status})`);
    }

    if (!response.ok) {
        throw new Error(data.error || `HTTP ${response.status}`);
    }
    return data;
}

// ==================== 声明性记忆模块 ====================

/**
 * 加载记忆预览（memory.md 原始内容）
 */
async function loadMemoryPreview() {
    const preview = document.getElementById('memory-preview');
    preview.innerHTML = '<span class="placeholder">加载中...</span>';

    try {
        const data = await apiCall('/api/memory');
        // 更新计数
        document.getElementById('memory-count').textContent = `${data.total} 条`;

        // 显示原始文件内容
        if (data.raw) {
            // 简单的语法高亮：标题、列表项、注释
            let html = data.raw
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                // 标题高亮
                .replace(/^(#{1,3}\s.+)$/gm, '<span style="color:var(--neon-cyan);font-weight:700;">$1</span>')
                // HTML 注释高亮
                .replace(/(&lt;!--.+?--&gt;)/g, '<span style="color:var(--text-muted);">$1</span>')
                // 引用块高亮
                .replace(/^(&gt;.+)$/gm, '<span style="color:var(--neon-yellow);">$1</span>')
                // 分隔线
                .replace(/^(-{3,})$/gm, '<span style="color:var(--neon-magenta);">$1</span>')
                // 列表项
                .replace(/^(-\s.+)$/gm, '<span style="color:var(--neon-green);">$1</span>');

            preview.innerHTML = html;
        } else {
            preview.innerHTML = '<span class="placeholder">memory.md 文件为空</span>';
        }
    } catch (err) {
        preview.innerHTML = `<span style="color:var(--neon-red);">加载失败: ${err.message}</span>`;
    }
}

/**
 * 打开 Remember 模态框
 */
function openRememberModal() {
    document.getElementById('remember-content').value = '';
    document.getElementById('remember-category').value = '';
    document.getElementById('remember-modal').style.display = 'flex';
    document.getElementById('remember-content').focus();
}

function closeRememberModal() {
    document.getElementById('remember-modal').style.display = 'none';
}

/**
 * 执行 Remember 命令
 */
async function executeRemember() {
    const content = document.getElementById('remember-content').value.trim();
    const category = document.getElementById('remember-category').value;

    if (!content) {
        showToast('memory', '内容不能为空', 'error');
        return;
    }

    closeRememberModal();

    const hasLLM = !category;
    const logs = hasLLM
        ? ['初始化记忆模块...', '调用 LLM 进行分类...', '分析内容语义...', '写入 memory.md...']
        : ['初始化记忆模块...', '验证分类信息...', '写入 memory.md...'];

    const progress = startProgress('memory', hasLLM ? 'REMEMBER // LLM 分类中' : 'REMEMBER // 添加中', logs);

    try {
        const result = await apiCall('/api/memory/remember', 'POST', { content, category: category || undefined });
        progress.complete(true, `已记住 [${result.category}]`);

        // 刷新预览
        setTimeout(() => loadMemoryPreview(), 500);
        showToast('memory', `已添加到 [${result.category}]: ${content.substring(0, 30)}...`, 'success');
    } catch (err) {
        progress.complete(false);
        showToast('memory', `添加失败: ${err.message}`, 'error');
    }
}

/**
 * 打开 Forget 模态框
 */
function openForgetModal() {
    document.getElementById('forget-keyword').value = '';
    document.getElementById('forget-modal').style.display = 'flex';
    document.getElementById('forget-keyword').focus();
}

function closeForgetModal() {
    document.getElementById('forget-modal').style.display = 'none';
}

/**
 * 执行 Forget 命令
 */
async function executeForget() {
    const keyword = document.getElementById('forget-keyword').value.trim();

    if (!keyword) {
        showToast('memory', '关键词不能为空', 'error');
        return;
    }

    closeForgetModal();

    const progress = startProgress('memory', 'FORGET // 删除中', [
        '搜索匹配条目...',
        '扫描所有分类...',
        '删除匹配项...',
    ]);

    try {
        const result = await apiCall('/api/memory/forget', 'POST', { keyword });
        progress.complete(true, `删除了 ${result.count} 条`);

        setTimeout(() => loadMemoryPreview(), 500);
        if (result.count > 0) {
            showToast('memory', `已删除 ${result.count} 条记忆`, 'success');
        } else {
            showToast('memory', `未找到包含"${keyword}"的记忆`, 'info');
        }
    } catch (err) {
        progress.complete(false);
        showToast('memory', `删除失败: ${err.message}`, 'error');
    }
}

/**
 * 触发 Refresh（打开模态框）
 * 自动从聊天区提取当前对话内容，填入 textarea 供用户确认
 */
function triggerRefresh() {
    // 从聊天消息区提取对话文本
    const conversation = extractChatConversation();
    document.getElementById('refresh-conversation').value = conversation;
    document.getElementById('refresh-modal').style.display = 'flex';

    // 如果对话内容为空，提示用户
    if (!conversation.trim()) {
        document.getElementById('refresh-conversation').placeholder =
            '当前对话为空，请先在上方对话框中进行几轮对话，再使用此功能提取偏好...';
    }
    document.getElementById('refresh-conversation').focus();
}

/**
 * 从聊天消息区提取对话文本
 * 遍历所有 .chat-message 元素，按角色拼接为 "用户: ...\n助手: ...\n" 格式
 *
 * @returns {string} 对话文本
 */
function extractChatConversation() {
    const messages = document.querySelectorAll('#chat-messages .chat-message');
    if (messages.length === 0) return '';

    const lines = [];
    for (const msg of messages) {
        // 跳过加载动画消息
        if (msg.classList.contains('loading')) continue;

        const bubble = msg.querySelector('.msg-bubble');
        if (!bubble) continue;

        const text = bubble.textContent.trim();
        if (!text) continue;

        if (msg.classList.contains('user')) {
            lines.push(`用户: ${text}`);
        } else if (msg.classList.contains('assistant')) {
            lines.push(`助手: ${text}`);
        }
    }
    return lines.join('\n\n');
}

function closeRefreshModal() {
    document.getElementById('refresh-modal').style.display = 'none';
}

/**
 * 执行 Refresh 命令
 */
async function executeRefresh() {
    const conversation = document.getElementById('refresh-conversation').value.trim();

    if (!conversation) {
        showToast('memory', '对话内容不能为空', 'error');
        return;
    }

    closeRefreshModal();

    const progress = startProgress('memory', 'REFRESH // LLM 提取偏好中', [
        '加载工作记忆...',
        '调用 LLM 分析对话...',
        '提取用户偏好...',
        '去重合并记忆...',
        '写入 memory.md...',
    ]);

    try {
        const result = await apiCall('/api/memory/refresh', 'POST', { conversation });

        if (result.total_added > 0) {
            progress.complete(true, `新增 ${result.total_added} 条记忆`);
            const details = Object.entries(result.added)
                .map(([cat, n]) => `${cat}: +${n}`)
                .join(' / ');
            showToast('memory', `提取完成: ${details}`, 'success');
        } else {
            progress.complete(true, '未发现新偏好');
            showToast('memory', '未从对话中发现新的偏好信息', 'info');
        }

        setTimeout(() => loadMemoryPreview(), 500);
    } catch (err) {
        progress.complete(false);
        showToast('memory', `提取失败: ${err.message}`, 'error');
    }
}


// ==================== 技能模块 ====================

/**
 * 加载技能列表
 */
async function loadSkills() {
    try {
        const data = await apiCall('/api/skills');
        const list = document.getElementById('skill-list');
        document.getElementById('skill-count').textContent = `${data.skills.length} 个`;

        list.innerHTML = '';

        for (const skill of data.skills) {
            const card = document.createElement('div');
            card.className = 'skill-card';

            // 关键词标签（最多显示 6 个）
            const keywords = skill.keywords.slice(0, 6)
                .map(kw => `<span class="skill-keyword">${kw}</span>`)
                .join('');
            const moreKeywords = skill.keywords.length > 6
                ? `<span class="skill-keyword">+${skill.keywords.length - 6}</span>`
                : '';

            // 已优化标记 + 恢复按钮（存在 .bak 备份时显示）
            const optimizedBadge = skill.has_backup
                ? `<span class="optimized-badge" title="此技能已优化保存过，可恢复原始版本">已优化</span>`
                : '';
            const restoreBtn = skill.has_backup
                ? `<button class="btn-ghost-sm restore-btn" onclick="restoreSkill('${skill.name}')">恢复原始</button>`
                : '';

            card.innerHTML = `
                <div class="skill-card-header">
                    <div class="skill-name-wrap">
                        <span class="skill-name">${skill.name}</span>
                        ${optimizedBadge}
                    </div>
                    <div class="skill-metrics">
                        <span>${skill.metrics.tokens} tok</span>
                        <span>${skill.metrics.chars} chars</span>
                        <span>${skill.metrics.rules} rules</span>
                    </div>
                </div>
                <div class="skill-desc">${skill.description}</div>
                <div class="skill-keywords">${keywords}${moreKeywords}</div>
                <div class="skill-actions">
                    <button class="btn-ghost-sm" onclick="viewSkillBody('${skill.name}')">查看正文</button>
                    <span class="goal-label">优化目标：</span>
                    <select class="goal-select" id="goal-${skill.name}">
                        <option value="token">Token 压缩</option>
                        <option value="speed">执行效率</option>
                        <option value="both">两者兼顾</option>
                    </select>
                    <button class="btn-ghost-sm save-btn" onclick="optimizeSkill('${skill.name}')">优化技能</button>
                    ${restoreBtn}
                </div>
                <!-- 就地结果展示区（优化对比/查看正文都显示在这里） -->
                <div class="skill-result" id="result-${skill.name}" style="display:none;"></div>
            `;
            list.appendChild(card);
        }
    } catch (err) {
        document.getElementById('skill-list').innerHTML =
            `<div style="color:var(--neon-red);padding:20px;font-family:var(--font-mono);font-size:12px;">加载失败: ${err.message}</div>`;
    }
}

/**
 * HTML 转义工具函数（防止技能正文中的特殊字符破坏 HTML 结构）
 * @param {string} text - 原始文本
 * @returns {string} 转义后的安全文本
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * 隐藏所有技能卡片的结果展示区
 * 在切换到新技能的查看/优化时调用，确保同一时间只有一个结果区展开
 */
function hideAllSkillResults() {
    document.querySelectorAll('.skill-result').forEach(el => {
        el.style.display = 'none';
        el.innerHTML = '';
    });
}

/**
 * 查看技能正文（就地展示在对应技能卡片下方）
 * @param {string} name - 技能名称
 */
async function viewSkillBody(name) {
    try {
        const data = await apiCall(`/api/skill/${name}/body`);

        // 隐藏其他技能的结果区（同一时间只展示一个）
        hideAllSkillResults();

        // 获取当前技能的就地结果容器
        const resultArea = document.getElementById(`result-${name}`);
        if (!resultArea) return;

        // 构建单边预览 HTML（只有"优化前"，不显示对比）
        resultArea.innerHTML = `
            <div class="result-header">
                <h3 class="section-label">技能正文: ${escapeHtml(name)}</h3>
                <div class="result-actions">
                    <button class="btn-ghost-sm" onclick="closeSkillResult('${name}')">关闭</button>
                </div>
            </div>
            <div class="compare-panes">
                <div class="compare-pane before" style="grid-column: 1 / -1;">
                    <div class="compare-header">
                        <span class="compare-metrics">${data.metrics.tokens} tokens | ${data.metrics.chars} chars | ${data.metrics.rules} rules</span>
                    </div>
                    <pre class="compare-content">${escapeHtml(data.body)}</pre>
                </div>
            </div>
        `;

        resultArea.style.display = 'block';
        // 平滑滚动到结果区（在卡片内部展开，不跳到页面底部）
        resultArea.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } catch (err) {
        showToast('skill', `加载失败: ${err.message}`, 'error');
    }
}

/**
 * 优化技能（结果就地展示在对应技能卡片下方）
 * @param {string} name - 技能名称
 */
async function optimizeSkill(name) {
    currentSkillName = name;

    // 读取用户选择的优化目标
    const goalSelect = document.getElementById(`goal-${name}`);
    const goal = goalSelect ? goalSelect.value : 'token';

    // 根据优化目标定制日志信息
    const goalLabel = {
        token: 'Token 压缩',
        speed: '执行效率',
        both: '两者兼顾',
    }[goal] || 'Token 压缩';

    const logs = [
        `加载技能 ${name}...`,
        `优化目标: ${goalLabel}`,
        '计算原始指标...',
        '调用 LLM 优化工作流...',
        '生成对比报告...',
    ];

    const progress = startProgress('skill', `OPTIMIZE // ${name} [${goalLabel}]`, logs);

    // 隐藏其他技能的结果区
    hideAllSkillResults();

    try {
        const result = await apiCall(`/api/skill/${name}/optimize`, 'POST', { goal });

        currentOptimizeData = result;
        progress.complete(true, '优化完成');

        // 展示对比结果（就地展示在技能卡片下方）
        displayOptimizeResult(result);

    } catch (err) {
        progress.complete(false);
        showToast('skill', `优化失败: ${err.message}`, 'error');
    }
}

/**
 * 展示优化对比结果（就地渲染到技能卡片的 result 容器中）
 * @param {Object} result - 优化接口返回的结果数据
 */
function displayOptimizeResult(result) {
    const name = result.skill_name;
    const resultArea = document.getElementById(`result-${name}`);
    if (!resultArea) return;

    // ---- 指标对比表 HTML ----
    const labelMap = {
        chars: '字符数', lines: '行数', tokens: 'Token数',
        words: '词数', rules: '规则数', sections: '章节数',
    };

    let tableHtml = `
        <div class="metrics-row header-row">
            <span class="metric-label">指标</span>
            <span>优化前</span>
            <span>优化后</span>
            <span>变化</span>
            <span class="metric-diff-pct">降幅</span>
        </div>
    `;

    for (const key of ['chars', 'lines', 'tokens', 'words', 'rules', 'sections']) {
        const o = result.original_metrics[key];
        const n = result.optimized_metrics[key];
        const diff = n - o;
        const pct = o > 0 ? `${(diff / o * 100).toFixed(1)}%` : 'N/A';
        const diffClass = diff < 0 ? 'down' : diff > 0 ? 'up' : '';
        const diffSign = diff > 0 ? '+' : '';

        tableHtml += `
            <div class="metrics-row data-row">
                <span class="metric-label">${labelMap[key]}</span>
                <span class="metric-before">${o}</span>
                <span class="metric-after">${n}</span>
                <span class="metric-diff ${diffClass}">${diffSign}${diff}</span>
                <span class="metric-diff ${diffClass} metric-diff-pct">${pct}</span>
            </div>
        `;
    }

    // ---- LLM 优化说明 ----
    const analysisHtml = result.llm_analysis
        ? `<div class="llm-analysis">
             <h4 class="sub-label">LLM 优化说明</h4>
             <div class="analysis-content">${escapeHtml(result.llm_analysis)}</div>
           </div>`
        : '';

    // ---- 前后对比预览 ----
    const origMetrics = result.original_metrics;
    const optMetrics = result.optimized_metrics;

    // 正文预览（限制显示前 60 行避免太长）
    const beforeLines = result.original_body.split('\n');
    const afterLines = result.optimized_body.split('\n');
    const maxLines = 60;

    const beforeText = beforeLines.length > maxLines
        ? beforeLines.slice(0, maxLines).join('\n') + `\n\n... (共 ${beforeLines.length} 行，已截断)`
        : result.original_body;

    const afterText = afterLines.length > maxLines
        ? afterLines.slice(0, maxLines).join('\n') + `\n\n... (共 ${afterLines.length} 行，已截断)`
        : result.optimized_body;

    // ---- 组装完整 HTML ----
    resultArea.innerHTML = `
        <div class="result-header">
            <h3 class="section-label">优化对比报告: ${escapeHtml(name)}</h3>
            <div class="result-actions">
                <button class="btn-save" id="save-btn-${name}" onclick="saveOptimizedSkill()">保存优化结果</button>
                <button class="btn-ghost-sm" onclick="closeSkillResult('${name}')">关闭</button>
            </div>
        </div>

        <!-- 指标对比表 -->
        <div class="metrics-table">${tableHtml}</div>

        <!-- LLM 优化说明 -->
        ${analysisHtml}

        <!-- 前后对比预览 -->
        <div class="compare-panes">
            <div class="compare-pane before">
                <div class="compare-header">
                    <span class="compare-tag before-tag">优化前</span>
                    <span class="compare-metrics">${origMetrics.tokens} tok | ${origMetrics.chars} chars | ${origMetrics.rules} rules</span>
                </div>
                <pre class="compare-content">${escapeHtml(beforeText)}</pre>
            </div>
            <div class="compare-pane after">
                <div class="compare-header">
                    <span class="compare-tag after-tag">优化后</span>
                    <span class="compare-metrics">${optMetrics.tokens} tok | ${optMetrics.chars} chars | ${optMetrics.rules} rules</span>
                </div>
                <pre class="compare-content">${escapeHtml(afterText)}</pre>
            </div>
        </div>
    `;

    resultArea.style.display = 'block';
    resultArea.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    // Token 节省提示
    const tokenSaved = origMetrics.tokens - optMetrics.tokens;
    if (tokenSaved > 0) {
        const pct = (tokenSaved / origMetrics.tokens * 100).toFixed(1);
        showToast('skill', `Token 节省 ${tokenSaved} 个 (${pct}%)`, 'success');
    }
}

/**
 * 保存优化后的技能
 *
 * 核心设计原则：
 * 1. 保存按钮在任何情况下都必须能恢复可用状态（成功/失败/异常）
 * 2. 已优化的技能也能正常保存（.bak 已存在时跳过备份，直接覆盖更新）
 * 3. 不清除 currentOptimizeData，允许用户多次点击保存
 */
async function saveOptimizedSkill() {
    // 前置检查：确保有优化数据可保存
    if (!currentOptimizeData || !currentSkillName) {
        showToast('skill', '无优化数据可保存，请先执行优化', 'error');
        return;
    }

    // 从当前技能的就地结果区中查找保存按钮
    const btn = document.getElementById(`save-btn-${currentSkillName}`);
    if (!btn) return;

    // 禁用按钮防止重复提交（API 返回后立即恢复）
    btn.textContent = '保存中...';
    btn.disabled = true;

    try {
        const result = await apiCall(`/api/skill/${currentSkillName}/save`, 'POST', {
            optimized_body: currentOptimizeData.optimized_body,
        });

        // 保存成功：按钮恢复可用，允许再次保存（即便是已优化的技能）
        btn.textContent = '已保存 ✓';
        btn.disabled = false;

        // 提示信息（区分首次保存和重复保存）
        if (result.backup_created) {
            showToast('skill', `已保存，原始版本备份为 ${currentSkillName}.md.bak`, 'success');
        } else {
            showToast('skill', `已保存（原始备份已保留，优化版本已更新）`, 'success');
        }

        // 刷新技能列表（更新指标显示和"已优化"标记）
        setTimeout(() => loadSkills(), 500);
    } catch (err) {
        // 保存失败：按钮必须恢复为可点击状态，确保用户能重试
        btn.textContent = '保存优化结果';
        btn.disabled = false;
        showToast('skill', `保存失败: ${err.message}`, 'error');
    }
}

/**
 * 关闭指定技能的就地结果展示区
 * @param {string} name - 技能名称
 */
function closeSkillResult(name) {
    const resultArea = document.getElementById(`result-${name}`);
    if (resultArea) {
        resultArea.style.display = 'none';
        resultArea.innerHTML = '';
    }
    // 清除全局状态（仅当关闭的是当前操作的技能时）
    if (name === currentSkillName) {
        currentOptimizeData = null;
        currentSkillName = null;
    }
}

/**
 * 从 .bak 备份恢复技能到原始版本
 * @param {string} name - 技能名称
 */
async function restoreSkill(name) {
    if (!confirm(`确定要恢复「${name}」到优化前的原始版本吗？\n当前优化后的内容将被覆盖。`)) return;

    try {
        await apiCall(`/api/skill/${name}/restore`, 'POST');
        showToast('skill', `「${name}」已恢复到原始版本`, 'success');
        // 刷新技能列表
        loadSkills();
    } catch (err) {
        showToast('skill', `恢复失败: ${err.message}`, 'error');
    }
}


// ==================== 对话模块 ====================

/**
 * 推理步骤类型的中文标签映射
 */
const TRACE_LABELS = {
    skill: 'SKILL',
    thought: 'THOUGHT',
    action: 'ACTION',
    observation: 'OBSERVE',
    final: 'FINAL',
};

let isChatting = false;  // 是否正在等待回复（防止重复发送）

/**
 * 检查当前是否开启流式模式
 * @returns {boolean} true=流式, false=非流式
 */
function isStreamMode() {
    const toggle = document.getElementById('stream-mode-toggle');
    return toggle ? toggle.checked : false;
}

/**
 * 发送消息（自动根据开关选择流式/非流式模式）
 * 1. 将用户消息追加到聊天区
 * 2. 显示加载动画
 * 3. 调用 /api/chat 或 /api/chat/stream 接口
 * 4. 展示 AI 回复 + ReAct 推理过程
 */
async function sendMessage() {
    const input = document.getElementById('chat-input');
    const message = input.value.trim();

    if (!message || isChatting) return;

    isChatting = true;
    const sendBtn = document.getElementById('chat-send-btn');
    sendBtn.disabled = true;

    // 重置分发面板（清空上一次的分发状态）
    resetDispatchPanel();

    // 清空输入框
    input.value = '';
    input.style.height = 'auto';

    // 移除欢迎信息（首次发送时）
    const welcome = document.querySelector('.chat-welcome');
    if (welcome) welcome.remove();

    // 追加用户消息
    appendMessage('user', message);

    // 显示加载动画
    const loadingEl = appendLoading();

    // 根据开关选择模式
    if (isStreamMode()) {
        await sendMessageStream(message, loadingEl);
    } else {
        await sendMessageNormal(message, loadingEl);
    }

    isChatting = false;
    sendBtn.disabled = false;
    document.getElementById('chat-input').focus();
}

/**
 * 非流式发送消息（原有逻辑，等待完整响应后一次性显示）
 * @param {string} message - 用户消息
 * @param {HTMLElement} loadingEl - 加载动画元素
 */
async function sendMessageNormal(message, loadingEl) {
    try {
        const result = await apiCall('/api/chat', 'POST', { message });

        // 移除加载动画
        loadingEl.remove();

        // 展示 AI 回复
        appendMessage('assistant', result.answer);

        // 展示推理过程
        if (result.trace && result.trace.length > 0) {
            displayTrace(result.trace);
        }

        // 更新记忆计数
        updateMemoryBadge(result.memory_size);
    } catch (err) {
        loadingEl.remove();
        appendMessage('assistant', `⚠️ 对话出错: ${err.message}`);
    }
}

/**
 * 流式发送消息（SSE 逐字接收，打字机效果）
 *
 * 实现方式：用 fetch + ReadableStream 解析 SSE 事件流
 * （不用 EventSource，因为 EventSource 只支持 GET 请求）
 *
 * @param {string} message - 用户消息
 * @param {HTMLElement} loadingEl - 加载动画元素
 */
async function sendMessageStream(message, loadingEl) {
    try {
        const response = await fetch('/api/chat/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message }),
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        // 移除加载动画，创建流式消息气泡
        loadingEl.remove();
        const msgEl = appendStreamingMessage();

        // 用于收集推理步骤
        const traceSteps = [];
        let fullAnswer = '';

        // 读取 SSE 流
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            // 将二进制数据解码为文本，追加到缓冲区
            buffer += decoder.decode(value, { stream: true });

            // SSE 事件以 "data: {json}\n\n" 格式分隔
            // 按双换行分割，取出完整的事件
            const lines = buffer.split('\n\n');
            // 最后一段可能不完整，保留在缓冲区
            buffer = lines.pop() || '';

            for (const line of lines) {
                const trimmed = line.trim();
                if (!trimmed.startsWith('data: ')) continue;

                // 解析 JSON 事件
                const jsonStr = trimmed.slice(6); // 去掉 "data: " 前缀
                try {
                    const event = JSON.parse(jsonStr);

                    if (event.type === 'trace') {
                        // 收集推理步骤
                        traceSteps.push(event.step);
                        // 实时更新推理区（逐步显示）
                        displayTrace(traceSteps);
                    } else if (event.type === 'dispatch') {
                        // 分发事件：实时更新 SubAgent 分发面板
                        handleDispatchEvent(event.data);
                    } else if (event.type === 'answer_chunk') {
                        // 追加回答片段到消息气泡（打字机效果）
                        fullAnswer += event.text;
                        updateStreamingMessage(msgEl, fullAnswer);
                    } else if (event.type === 'done') {
                        // 全部完成
                        finishStreamingMessage(msgEl);
                        updateMemoryBadge(event.memory_size);
                    } else if (event.type === 'error') {
                        throw new Error(event.message);
                    }
                } catch (parseErr) {
                    // JSON 解析失败时跳过该事件
                    console.warn('SSE 事件解析失败:', parseErr);
                }
            }
        }

        // 如果没有收到任何回答片段，显示提示
        if (!fullAnswer) {
            updateStreamingMessage(msgEl, '（未收到有效回复）');
            finishStreamingMessage(msgEl);
        }
    } catch (err) {
        loadingEl.remove();
        appendMessage('assistant', `⚠️ 对话出错: ${err.message}`);
    }
}

/**
 * 创建流式消息气泡（空的，等待逐步填充）
 * @returns {HTMLElement} 消息元素（用于后续更新内容）
 */
function appendStreamingMessage() {
    const messages = document.getElementById('chat-messages');
    const msg = document.createElement('div');
    msg.className = 'chat-message assistant streaming';
    msg.innerHTML = `
        <div class="msg-avatar">AI</div>
        <div class="msg-content-wrap">
            <div class="msg-bubble"><span class="streaming-cursor">▋</span></div>
        </div>
    `;
    insertMessage(messages, msg);
    return msg;
}

/**
 * 更新流式消息内容（打字机效果）
 * @param {HTMLElement} msgEl - 消息元素
 * @param {string} text - 当前累积的完整文本
 */
function updateStreamingMessage(msgEl, text) {
    const bubble = msgEl.querySelector('.msg-bubble');
    if (!bubble) return;
    // 文本 + 闪烁光标
    bubble.innerHTML = `${escapeHtml(text)}<span class="streaming-cursor">▋</span>`;
    scrollToBottom();
}

/**
 * 流式消息完成（移除光标，添加复制按钮）
 * @param {HTMLElement} msgEl - 消息元素
 */
function finishStreamingMessage(msgEl) {
    const bubble = msgEl.querySelector('.msg-bubble');
    if (!bubble) return;

    // 移除光标
    const cursor = bubble.querySelector('.streaming-cursor');
    if (cursor) cursor.remove();

    // 移除 streaming 类
    msgEl.classList.remove('streaming');

    // 添加复制按钮
    const wrap = msgEl.querySelector('.msg-content-wrap');
    if (wrap && !wrap.querySelector('.msg-copy-btn')) {
        const copyBtn = document.createElement('button');
        copyBtn.className = 'msg-copy-btn';
        copyBtn.title = '复制消息';
        copyBtn.innerHTML = '<span class="copy-icon">⎘</span><span class="copy-text">复制</span>';
        copyBtn.onclick = () => copyMessage(copyBtn);
        wrap.appendChild(copyBtn);
    }
}

/**
 * 追加一条消息到聊天区
 * @param {string} role - 'user' 或 'assistant'
 * @param {string} text - 消息内容
 */
function appendMessage(role, text) {
    const messages = document.getElementById('chat-messages');
    const msg = document.createElement('div');
    msg.className = `chat-message ${role}`;

    const avatar = role === 'user' ? 'U' : 'AI';
    msg.innerHTML = `
        <div class="msg-avatar">${avatar}</div>
        <div class="msg-content-wrap">
            <div class="msg-bubble">${escapeHtml(text)}</div>
            <button class="msg-copy-btn" onclick="copyMessage(this)" title="复制消息">
                <span class="copy-icon">⎘</span>
                <span class="copy-text">复制</span>
            </button>
        </div>
    `;
    insertMessage(messages, msg);
}

/**
 * 复制消息内容到剪贴板
 * @param {HTMLElement} btn - 被点击的复制按钮
 */
function copyMessage(btn) {
    const wrap = btn.parentElement;
    const bubble = wrap.querySelector('.msg-bubble');
    if (!bubble) return;

    const text = bubble.textContent.trim();

    // 使用 navigator.clipboard API（现代浏览器）
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => {
            showCopySuccess(btn);
        }).catch(() => {
            fallbackCopy(text, btn);
        });
    } else {
        fallbackCopy(text, btn);
    }
}

/**
 * 备用复制方法（兼容旧浏览器）
 */
function fallbackCopy(text, btn) {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    try {
        document.execCommand('copy');
        showCopySuccess(btn);
    } catch (e) {
        console.error('复制失败:', e);
    }
    document.body.removeChild(textarea);
}

/**
 * 显示复制成功反馈
 */
function showCopySuccess(btn) {
    const textEl = btn.querySelector('.copy-text');
    const originalText = textEl.textContent;
    textEl.textContent = '已复制';
    btn.classList.add('copied');
    setTimeout(() => {
        textEl.textContent = originalText;
        btn.classList.remove('copied');
    }, 1500);
}

/**
 * 追加加载动画
 * @returns {HTMLElement} 加载动画元素（用于后续移除）
 */
function appendLoading() {
    const messages = document.getElementById('chat-messages');
    const msg = document.createElement('div');
    msg.className = 'chat-message assistant loading';
    msg.innerHTML = `
        <div class="msg-avatar">AI</div>
        <div class="msg-bubble">
            <div class="loading-dots">
                <span></span><span></span><span></span>
            </div>
        </div>
    `;
    insertMessage(messages, msg);
    return msg;
}

/**
 * 展示 ReAct 推理过程
 * @param {Array} trace - 推理步骤列表 [{type, text}, ...]
 */
function displayTrace(trace) {
    const area = document.getElementById('react-trace-area');
    const body = document.getElementById('trace-body');
    const countEl = document.getElementById('trace-step-count');

    // 清空旧的推理过程
    body.innerHTML = '';

    // 追加每个步骤
    for (const step of trace) {
        const stepEl = document.createElement('div');
        stepEl.className = 'trace-step';
        stepEl.dataset.type = step.type;
        stepEl.innerHTML = `
            <span class="step-tag">${TRACE_LABELS[step.type] || step.type.toUpperCase()}</span>
            <span class="step-text">${escapeHtml(step.text)}</span>
        `;
        body.appendChild(stepEl);
    }

    // 更新步骤数
    countEl.textContent = `${trace.length} 步`;

    // 显示并自动展开推理区
    area.style.display = 'block';
    area.classList.remove('collapsed');
}

/**
 * 折叠/展开推理过程
 */
function toggleTrace() {
    const area = document.getElementById('react-trace-area');
    if (!area) return;
    area.classList.toggle('collapsed');
}

/**
 * 折叠/展开 SubAgent 分发面板
 */
function toggleDispatch() {
    const panel = document.getElementById('dispatch-panel');
    if (!panel) return;
    panel.classList.toggle('collapsed');
}

// ==================== SubAgent 分发流程图可视化 ====================

/**
 * 分发状态追踪
 */
let dispatchState = null;

/**
 * 处理分发事件（从 SSE 流接收）
 *
 * 事件流程：
 *   dispatch_start → start(n次) → complete(n次) → all_done
 *
 * 流程图动画顺序：
 *   [Main Agent] →连线→ [DispatchManager] →分叉→ [SubAgents] →汇合→ [Aggregation]
 *
 * @param {Object} data - 分发事件数据
 */
function handleDispatchEvent(data) {
    const panel = document.getElementById('dispatch-panel');
    if (!panel) return;

    switch (data.phase) {
        case 'dispatch_start': {
            // 初始化流程图面板：显示并展开
            panel.style.display = 'block';
            panel.classList.remove('collapsed', 'dispatch-done');

            // 更新状态文本
            const statusText = document.getElementById('dispatch-status-text');
            if (statusText) statusText.textContent = `${data.total} 任务 · ${data.max_workers} 并发`;

            // 重置所有节点状态
            const dispatcherInfo = document.getElementById('flow-dispatcher-info');
            const aggregationInfo = document.getElementById('flow-aggregation-info');
            if (dispatcherInfo) dispatcherInfo.textContent = '准备分发...';
            if (aggregationInfo) aggregationInfo.textContent = '等待中...';

            // 重置连线动画
            ['flow-line-1', 'flow-branch', 'flow-merge'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.classList.remove('animated');
            });

            // 重置节点状态
            ['flow-main-agent', 'flow-dispatcher', 'flow-aggregation'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.classList.remove('active', 'done');
            });

            // 初始化分发状态
            dispatchState = {
                total: data.total,
                stocks: data.stocks || [],
                maxWorkers: data.max_workers || 3,
                agents: {},
                startTime: Date.now(),
            };

            // 创建 SubAgent 节点
            const subagentsContainer = document.getElementById('flow-subagents');
            if (subagentsContainer) {
                subagentsContainer.innerHTML = '';
                for (let i = 0; i < data.total; i++) {
                    const agentId = `subagent_${i}`;
                    const stock = data.stocks[i] || '?';
                    dispatchState.agents[agentId] = { stock, status: 'pending', duration: 0 };
                    const node = createSubAgentNode(agentId, stock, i, data.total);
                    subagentsContainer.appendChild(node);
                }
            }

            // 动画：Main Agent 激活 → 连线绘制 → DispatchManager 激活
            setTimeout(() => {
                activateNode('flow-main-agent');
                animateConnector('flow-line-1');
                setTimeout(() => {
                    activateNode('flow-dispatcher');
                    if (dispatcherInfo) {
                        dispatcherInfo.textContent = `${data.total} 任务 · ${data.max_workers} 并发`;
                    }
                    // 分叉连线动画
                    setTimeout(() => {
                        animateConnector('flow-branch');
                    }, 300);
                }, 400);
            }, 100);
            break;
        }

        case 'start': {
            // SubAgent 开始执行
            if (!dispatchState) return;
            dispatchState.agents[data.agent_id].status = 'running';
            updateSubAgentNode(data.agent_id, 'running');
            break;
        }

        case 'complete': {
            // SubAgent 完成
            if (!dispatchState) return;
            const agent = dispatchState.agents[data.agent_id];
            agent.status = data.status;
            agent.duration = data.duration;
            updateSubAgentNode(data.agent_id, data.status, data.duration);

            // 检查是否全部完成
            const allDone = Object.values(dispatchState.agents).every(
                a => a.status === 'ok' || a.status === 'error'
            );
            if (allDone) {
                // 汇合连线动画
                setTimeout(() => {
                    animateConnector('flow-merge');
                    setTimeout(() => activateNode('flow-aggregation'), 400);
                }, 200);
            }
            break;
        }

        case 'all_done': {
            if (!dispatchState) return;
            const elapsed = data.duration || 0;
            const completed = Object.values(dispatchState.agents).filter(a => a.status === 'ok').length;
            const failed = Object.values(dispatchState.agents).filter(a => a.status === 'error').length;

            // 更新聚合节点信息
            const aggInfo = document.getElementById('flow-aggregation-info');
            if (aggInfo) {
                aggInfo.textContent = `${completed}/${data.total} 完成` +
                    (failed > 0 ? ` · ${failed} 失败` : '') +
                    ` · ${elapsed}s`;
            }

            // 更新面板状态文本
            const statusText = document.getElementById('dispatch-status-text');
            if (statusText) {
                statusText.textContent = `${completed}/${data.total} 完成 · ${elapsed}s`;
            }

            // 标记 Main Agent 和 DispatchManager 为完成
            const mainAgent = document.getElementById('flow-main-agent');
            const dispatcher = document.getElementById('flow-dispatcher');
            if (mainAgent) mainAgent.classList.add('done');
            if (dispatcher) dispatcher.classList.add('done');

            panel.classList.add('dispatch-done');
            break;
        }
    }

    scrollToBottom();
}

/**
 * 创建 SubAgent 流程图节点
 * @param {string} agentId - Agent ID (如 "subagent_0")
 * @param {string} stock - 股票名称
 * @param {number} index - 索引
 * @param {number} total - 总数
 * @returns {HTMLElement} 节点元素
 */
function createSubAgentNode(agentId, stock, index, total) {
    const node = document.createElement('div');
    node.className = 'flow-node flow-subagent status-pending';
    node.id = `flow-agent-${agentId}`;
    node.style.animationDelay = `${index * 0.15}s`;

    // 根据总数调整节点宽度（避免过多时溢出）
    if (total > 4) {
        node.classList.add('compact');
    }

    node.innerHTML = `
        <div class="node-icon agent-avatar">
            <span class="agent-num">${index + 1}</span>
        </div>
        <div class="node-body">
            <span class="node-title">${escapeHtml(stock)}</span>
            <span class="node-subtitle">${escapeHtml(agentId)}</span>
        </div>
        <div class="node-status-badge">
            <span class="status-dot"></span>
            <span class="status-label">等待中</span>
        </div>
        <div class="node-duration"></div>
    `;
    return node;
}

/**
 * 更新 SubAgent 节点状态
 * @param {string} agentId - Agent ID
 * @param {string} status - 新状态: running / ok / error
 * @param {number} [duration] - 执行耗时（秒）
 */
function updateSubAgentNode(agentId, status, duration) {
    const node = document.getElementById(`flow-agent-${agentId}`);
    if (!node) return;

    // 更新状态类名
    node.className = node.className.replace(/status-\w+/g, '');
    node.classList.add(`status-${status}`);

    // 更新状态标签
    const statusLabel = node.querySelector('.status-label');
    if (statusLabel) {
        const labels = { pending: '等待中', running: '执行中', ok: '完成', error: '失败' };
        statusLabel.textContent = labels[status] || status;
    }

    // 更新耗时
    const durationEl = node.querySelector('.node-duration');
    if (durationEl && duration !== undefined) {
        durationEl.textContent = `${duration}s`;
    }

    // 完成时添加涟漪效果
    if (status === 'ok' || status === 'error') {
        const ripple = document.createElement('div');
        ripple.className = `ripple ripple-${status}`;
        node.appendChild(ripple);
        setTimeout(() => ripple.remove(), 1000);
    }
}

/**
 * 激活流程图节点（添加 active 类触发动画）
 * @param {string} nodeId - 节点元素 ID
 */
function activateNode(nodeId) {
    const node = document.getElementById(nodeId);
    if (node) {
        node.classList.add('active');
    }
}

/**
 * 触发连线绘制动画
 * @param {string} connectorId - 连线元素 ID
 */
function animateConnector(connectorId) {
    const connector = document.getElementById(connectorId);
    if (connector) {
        connector.classList.add('animated');
    }
}

/**
 * 重置分发面板（在新对话开始时调用）
 */
function resetDispatchPanel() {
    const panel = document.getElementById('dispatch-panel');
    if (panel) {
        panel.style.display = 'none';
        panel.classList.remove('dispatch-done', 'collapsed');
    }
    const statusText = document.getElementById('dispatch-status-text');
    if (statusText) statusText.textContent = '';
    const subagentsContainer = document.getElementById('flow-subagents');
    if (subagentsContainer) {
        subagentsContainer.innerHTML = '';
    }
    // 重置节点和连线
    ['flow-main-agent', 'flow-dispatcher', 'flow-aggregation'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.classList.remove('active', 'done');
    });
    ['flow-line-1', 'flow-branch', 'flow-merge'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.classList.remove('animated');
    });
    dispatchState = null;
}

/**
 * 清空对话（重置工作记忆）
 */
async function clearChat() {
    if (!confirm('确定要清空对话记忆吗？这将重置多轮对话上下文。')) return;

    try {
        await apiCall('/api/chat/clear', 'POST');
        // 清空消息区（仅恢复欢迎页，trace/dispatch 已在外部不需要重建）
        const messages = document.getElementById('chat-messages');
        messages.innerHTML = `
            <div class="chat-welcome">
                <div class="welcome-emoji">👋</div>
                <div class="welcome-text">
                    <strong>HARNESS ReAct Agent 已就绪</strong>
                    <p>输入问题开始对话，支持多轮上下文、工具调用与技能路由。</p>
                    <div class="welcome-examples">
                        <span class="example-chip">帮我找一首描写思乡的古诗</span>
                        <span class="example-chip">北京今天天气怎么样</span>
                        <span class="example-chip">帮我背单词</span>
                    </div>
                </div>
            </div>
        `;
        // 隐藏推理区和分发面板
        document.getElementById('react-trace-area').style.display = 'none';
        resetDispatchPanel();
        updateMemoryBadge(0);
        showToast('memory', '对话记忆已清空', 'info');
    } catch (err) {
        showToast('memory', `清空失败: ${err.message}`, 'error');
    }
}

/**
 * 更新记忆计数徽章
 */
function updateMemoryBadge(size) {
    document.getElementById('chat-memory-badge').textContent = `记忆: ${size} 条`;
}

/**
 * 将消息元素追加到 chat-messages 中
 * trace/dispatch 已移出消息区，消息直接 append 即可
 * @param {HTMLElement} container - chat-messages 容器
 * @param {HTMLElement} msgEl - 要插入的消息元素
 */
function insertMessage(container, msgEl) {
    container.appendChild(msgEl);
    scrollToBottom();
}

/**
 * 滚动到消息底部
 * 同时滚动信息面板区，确保最新的 trace/dispatch 内容可见
 */
function scrollToBottom() {
    const messages = document.getElementById('chat-messages');
    messages.scrollTop = messages.scrollHeight;

    // 同步滚动信息面板区（trace/dispatch）
    const infoPanels = document.getElementById('chat-info-panels');
    if (infoPanels) {
        infoPanels.scrollTop = infoPanels.scrollHeight;
    }
}

/**
 * 输入框自动高度 + Enter 发送
 */
function initChatInput() {
    const input = document.getElementById('chat-input');

    // 自动调整高度
    input.addEventListener('input', () => {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 120) + 'px';
    });

    // Enter 发送，Shift+Enter 换行
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
}


// ==================== 初始化 ====================

// 页面加载完成后启动
document.addEventListener('DOMContentLoaded', () => {
    // 启动时钟
    updateClock();
    setInterval(updateClock, 1000);

    // 加载技能列表
    loadSkills();

    // 初始化对话输入框
    initChatInput();

    // 示例问题点击 → 自动填入输入框并发送
    document.addEventListener('click', (e) => {
        if (e.target.classList.contains('example-chip')) {
            const input = document.getElementById('chat-input');
            input.value = e.target.textContent;
            sendMessage();
        }
    });

    // ESC 关闭模态框
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeRememberModal();
            closeForgetModal();
            closeRefreshModal();
        }
    });

    // 点击遮罩关闭模态框
    document.querySelectorAll('.modal-overlay').forEach(overlay => {
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) {
                overlay.style.display = 'none';
            }
        });
    });
});
