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





#补充kvchache的代码
from torch.utils.data import Dataset
from torch.utils.data import DataLoader
from torch.utils.data import random_split
from torch.utils.data import TensorDataset
from torch.utils.data import random_split
from torch.utils.data import DataLoader

class KVCache(Dataset):
    def __init__(self, data, labels):
        self.data = data
        self.labels = labels
    def __len__(self):
        return len(self.data)
    def __getitem__(self, idx):
        return self.data[idx], self.labels[idx] 


def train():
    pass



#补充transformer的代码
def test():
    pass


#输出一个简单的transformer模型
def output_transformer():
    pass
