## dataset.py

import os
import random
import numpy as np
from typing import List, Dict, Tuple

import torch
from torch.utils.data import Dataset
from torch.nn.utils.rnn import pad_sequence


def parse_sample_file(file_path: str) -> Dict:
    """
    解析单个样本文件，保留全部帧信息（不裁切）
    返回结构：{
      'frames': np.array (N, 63),
      'frame_ids': np.array (N,),
      'drop_frame': int,
      'label_xyz': np.array (3,)
    }
    """
    with open(file_path, 'r') as f:
        lines = [ln.strip() for ln in f if ln.strip()]

    if len(lines) < 2:
        raise ValueError(f"文件行数太少: {file_path}")

    # 最后一行是落点
    last_line = lines[-1]
    drop_frame_str, drop_xyz_str = last_line.split(":")
    drop_frame = int(drop_frame_str)
    drop_xyz = np.array(list(map(float, drop_xyz_str.split(","))), dtype=np.float32)
    # print(drop_frame, drop_xyz)

    frame_ids = []
    frames = []
    for ln in lines[:-1]:
        fid_str, coords_str = ln.split(":")
        fid = int(fid_str)
        coords = np.array(list(map(float, coords_str.split(","))), dtype=np.float32)
        if len(coords) != 63:
            coords = coords[:63]
        frame_ids.append(fid)
        frames.append(coords)

    return {
        'frames': np.stack(frames, axis=0),
        'frame_ids': np.array(frame_ids, dtype=np.int32),
        'drop_frame': drop_frame,
        'label_xyz': drop_xyz
    }


def load_all_samples(folder: str, suffix='.txt') -> List[Dict]:
    samples = []
    for fn in sorted(os.listdir(folder)):
        if not fn.endswith(suffix):
            continue
        path = os.path.join(folder, fn)
        try:
            s = parse_sample_file(path)
            samples.append(s)
        except Exception as e:
            print(f"跳过 {fn}: {e}")
    return samples

def collate_fn_dynamic(batch):
    """
    batch: list of tuples (seq, length, label_xyz, label_time)
    seq: (seq_len_i, feature_dim)
    length: int
    label_xyz: (3,)
    label_time: float

    返回：
        seqs_padded: (B, max_len, feature_dim)
        lengths: (B,)
        xyzs: (B,3)
        times: (B,)
        mask: (B, max_len)
    """
    seqs, lengths, xyzs, times = zip(*batch)
    lengths = torch.tensor(lengths, dtype=torch.long)
    feature_dim = seqs[0].shape[1]
    max_len = max(lengths)

    seqs_padded = []
    masks = []

    for seq, l in zip(seqs, lengths):
        pad_len = max_len - l
        if pad_len > 0:
            pad = torch.zeros(pad_len, feature_dim, dtype=seq.dtype)
            seq_padded = torch.cat([pad, seq], dim=0)
        else:
            seq_padded = seq
        mask = torch.ones(max_len, dtype=torch.bool)  # 先全设为True（默认填充）
        mask[:pad_len] = False  # 将前pad_l个位置设为False

        seqs_padded.append(seq_padded)
        masks.append(mask)

    seqs_padded = torch.stack(seqs_padded, dim=0)  # (B, max_len, feature_dim)
    masks = torch.stack(masks, dim=0)              # (B, max_len)
    xyzs = torch.stack(xyzs, dim=0)                # (B,3)
    times = torch.stack(times, dim=0)              # (B,)

    return seqs_padded, lengths, masks, xyzs, times

def resampling(samples: List[Dict],
                num_subsamples: int = 5,
                min_len: int = 10,
                max_len: int = 50) -> Tuple[List[Dict], List[Dict]]:
    """
    将原始样本扩展成多个子样本。

    Args:
        samples: 原始样本，每个 sample 包含 frames, frame_ids, drop_frame, label_xyz
        num_subsamples: 每条样本扩展的子样本数
        min_len, max_len: 每个子样本的帧长度范围

    Returns:
        train_samples, test_samples
    """
    expanded_samples = []
    for s in samples:
        total_len = len(s["frames"])
        for k in range(num_subsamples):
            seq_len = np.random.randint(min_len, max_len + 1)
            if seq_len > total_len:
                continue
            # 随机从结尾往前取一段
            end_idx = np.random.randint(seq_len - 1, total_len)
            start_idx = end_idx - seq_len + 1

            sub_sample = {
                "frames": s["frames"][start_idx:end_idx+1],
                "frame_ids": s["frame_ids"][start_idx:end_idx+1],
                "drop_frame": s["drop_frame"],
                "label_xyz": s["label_xyz"]
            }
            expanded_samples.append(sub_sample)

    # 打乱并划分
    random.shuffle(expanded_samples)
    return expanded_samples

def resampling_v2(samples: List[Dict],
                num_subsamples: int = 5) -> Tuple[List[Dict], List[Dict]]:
    """
    将原始样本扩展成多个子样本。

    Args:
        samples: 原始样本，每个 sample 包含 frames, frame_ids, drop_frame, label_xyz
        num_subsamples: 每条样本扩展的子样本数
        min_len, max_len: 每个子样本的帧长度范围

    Returns:
        train_samples, test_samples
    """
    expanded_samples = []
    for s in samples:
        total_len = len(s["frames"])
        for k in range(num_subsamples):
            sub_sample = {
                "frames": s["frames"],
                "frame_ids": s["frame_ids"],
                "drop_frame": s["drop_frame"],
                "label_xyz": s["label_xyz"]
            }
            expanded_samples.append(sub_sample)

    # 打乱并划分
    random.shuffle(expanded_samples)
    return expanded_samples

def down_sampling(samples: List[Dict],
                min_len: int = 10,
                max_len: int = 50) -> Tuple[List[Dict], List[Dict]]:
    """
    将原始样本进行抽帧。

    Args:
        samples: 原始样本，每个 sample 包含 frames, frame_ids, drop_frame, label_xyz
        min_len, max_len: 每个子样本的帧长度范围

    Returns:
        train_samples, test_samples
    """
    expanded_samples = []
    total_len = len(samples[0]["frames"])
    for s in samples:
        seq_len = np.random.randint(min_len, max_len + 1)
        start_idx = total_len - seq_len + 1

        sub_sample = {
            "frames": s["frames"][start_idx:total_len],
            "frame_ids": s["frame_ids"][start_idx:total_len],
            "drop_frame": s["drop_frame"],
            "label_xyz": s["label_xyz"]
        }
        expanded_samples.append(sub_sample)

    # 打乱并划分
    random.shuffle(expanded_samples)
    return expanded_samples

class BadmintonDataset(Dataset):
    def __init__(self, samples: List[Dict], min_len: int = 10, max_len: int = 50,
                 mode: str = "train",
                 num_subsamples: int = 5, # not use
                 feature_mean=None, feature_std=None,
                 label_mean=None, label_std=None):
        super().__init__()
        assert len(samples) > 0
        self.samples = samples
        self.min_len = min_len
        self.max_len = max_len
        self.mode = mode


        if mode == "train":
            # 统计归一化参数（仅初始化时统计一次）
            all_features = np.concatenate([s["frames"] for s in samples], axis=0)
            all_labels = np.stack([np.concatenate([s["label_xyz"], [s["drop_frame"] - s["frame_ids"][-1]]])
                                    for s in samples], axis=0)
            self.feature_mean = all_features.mean(axis=0, keepdims=True)
            self.feature_std = all_features.std(axis=0, keepdims=True) + 1e-6
            self.label_mean = all_labels.mean(axis=0, keepdims=True)
            self.label_std = all_labels.std(axis=0, keepdims=True) + 1e-6
            self.noise_std_x = self.label_std[0][0]/5 # 176.7 * 0.1（可后续调为1/8或1/5倍）
            self.noise_std_y = self.label_std[0][1]/5  # 181.86 * 0.1

            # resampling_v2, 每个样本copy几份
            self.samples = resampling_v2(self.samples, num_subsamples)
        else:
            # 验证/测试：使用训练集的统计量
            self.feature_mean = feature_mean
            self.feature_std = feature_std
            self.label_mean = label_mean
            self.label_std = label_std

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        s = self.samples[idx]
        total_frames = s["frames"]
        total_frame_ids = s["frame_ids"]
        drop_frame = s["drop_frame"]

        # 动态生成子样本（仅训练时随机截取，测试时取固定长度）
        if self.mode == "train":
            total_len = len(total_frames)
            seq_len = np.random.randint(self.min_len, self.max_len + 1)
            if seq_len > total_len:
                seq_len = total_len  # 防止长度超过原始序列
            # end_idx = np.random.randint(seq_len - 1, total_len)
            end_idx = total_len - 1
            start_idx = end_idx - seq_len + 1
        else:
            # 测试时：从结尾取固定长度（或保持原始逻辑）
            total_len = len(total_frames)
            seq_len = self.max_len
            start_idx = total_len - seq_len  # 从结尾取
            end_idx = total_len - 1

        # 截取子样本
        seq = torch.from_numpy(total_frames[start_idx:end_idx+1]).float()
        frame_ids = total_frame_ids[start_idx:end_idx+1]
        length = seq.shape[0]
        label_xyz_raw = torch.tensor(s["label_xyz"], dtype=torch.float32)  # 原始XY轴标签（物理空间）
        label_time_raw = torch.tensor(drop_frame - frame_ids[-1], dtype=torch.float32)  # 时间标签（暂不加噪声）

        # 归一化
        seq = (seq - torch.from_numpy(self.feature_mean).float()) / torch.from_numpy(self.feature_std).float()
        # 训练集专属：XY轴标签加噪声（核心步骤）
        # if self.mode == "train":
        #     # 2.1 确保噪声在原始物理空间添加（先反归一化？不——这里label_xyz_raw是原始空间，无需反归一化）
        #     # 生成高斯噪声（与标签同设备、同 dtype）
        #     noise_x = torch.normal(mean=0.0, std=self.noise_std_x, size=[], dtype=label_xyz_raw.dtype, device=label_xyz_raw.device)
        #     noise_y = torch.normal(mean=0.0, std=self.noise_std_y, size=[], dtype=label_xyz_raw.dtype, device=label_xyz_raw.device)
        #     # 给XY轴标签加噪声（Z轴若无需增强可跳过）
        #     label_xyz_raw[0] += noise_x  # X轴加噪声
        #     label_xyz_raw[1] += noise_y  # Y轴加噪声
        
        label_all = torch.cat([label_xyz_raw, label_time_raw.unsqueeze(0)], dim=0)
        label_all = (label_all - torch.from_numpy(self.label_mean).squeeze(0).float()) / \
                    torch.from_numpy(self.label_std).squeeze(0).float()

        label_xyz_norm = label_all[:3]
        label_time_norm = label_all[3]

        return seq, torch.tensor(length, dtype=torch.long), label_xyz_norm, label_time_norm
    
    def get_norm_stats(self):
        return self.feature_mean, self.feature_std, self.label_mean, self.label_std
    

if __name__ == "__main__": 
    # path = '/home/zhaoxuhao/badminton_xh/20250809_Seq_data/20250809_150058---008377.txt' 
    import argparse 
    parser = argparse.ArgumentParser() 
    # parser.add_argument('--data_folder', type=str, default='/home/zhaoxuhao/badminton_xh/20250809_Seq_data') 
    parser.add_argument('--data_folder', type=str, default='/home/zhaoxuhao/badminton_xh/20250809_Seq_data_v2/20250809_Seq_data')
    args = parser.parse_args() 
    # 加载所有样本 
    samples = load_all_samples(args.data_folder) 
    print(f"一共加载到 {len(samples)} 个样本") # print(samples) 
    # 构建 Dataset 
    dataset = BadmintonDataset(samples, mode='train', min_len=10, max_len=50) 
    feature_mean, feature_std, label_mean, label_std = dataset.get_norm_stats()
    test_dataset = BadmintonDataset(samples, mode='test', min_len=10, max_len=50,
                               feature_mean=feature_mean, feature_std=feature_std,
                               label_mean=label_mean, label_std=label_std)

    # 4. 打印
    print("========== 数据集统计信息 ==========")
    print(f"特征 mean: {feature_mean.shape}, 示例前5个维度: {feature_mean[0, :5]}")
    print(f"特征 std : {feature_std.shape}, 示例前5个维度: {feature_std[0, :5]}")

    print(f"标签 mean: {label_mean.shape}, 值: {label_mean[0]}")
    print(f"标签 std : {label_std.shape}, 值: {label_std[0]}")

    # 随机取几个看看 
    for i in range(5): 
        xyz_seq, seq_len, label_xyz, label_t = dataset[i] 
        print(f"样本 {i}:") 
        print(f" 输入序列 shape: {xyz_seq.shape}") # (L, 63), L ∈ [40, 50] 
        print(f" seq len: {seq_len}") 
        print(f" 落点 label xyz: {label_xyz.numpy()}") 
        print(f" 飞行时间 label: {label_t.item()}")

    print("\ntest data")
    # 随机取几个看看 
    for i in range(5): 
        xyz_seq, seq_len, label_xyz, label_t = test_dataset[i] 
        print(f"样本 {i}:") 
        print(f" 输入序列 shape: {xyz_seq.shape}") # (L, 63), L ∈ [40, 50] 
        print(f" seq len: {seq_len}") 
        print(f" 落点 label xyz: {label_xyz.numpy()}") 
        print(f" 飞行时间 label: {label_t.item()}")
