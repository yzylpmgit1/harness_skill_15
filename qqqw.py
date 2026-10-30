#写一个简单的transformer框架代码
import torch
import torch.nn as nn
import torch.nn.functional as F
class Transformer(nn.Module):
    def __init__(self):
        super().__init__()
        self.embedding = nn.Embedding(100, 512)
        self.self_attn = nn.MultiheadAttention(512, 8)
    def forward(self, x):
        x = self.embedding(x)
        x = self.self_attn(x, x, x)
        return x


