'''
@Author: Xiao Tong
@FileName: utils.py
@CreateTime: 2022-03-22 20:51:50
@Description:

'''

import os
import tqdm
import torch
import pickle
import logging
import datetime
import numpy as np
from gensim.utils import tokenize
from collections import OrderedDict


def getLogger(log_dir: str, model_name: str, name: str="log") -> logging.Logger:
    """
    @param: log_dir: directory to save log files
    @param: name: logger name
    """
    logger = logging.Logger(name=name, level=logging.INFO)
    if not os.path.isdir(log_dir):
        os.makedirs(log_dir)

    now = datetime.datetime.now()
    filename = "{}_{}.log".format(model_name, now.strftime("%Y-%m-%d_%H:%M:%S"))
    formatter = logging.Formatter(fmt="%(asctime)s - %(filename)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    file_handler = logging.FileHandler(os.path.join(log_dir, filename), mode="w", encoding="utf-8")
    stream_handler = logging.StreamHandler()
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


def get_stopwords(stopwords_file: str) -> list:
    stopwords = []
    with open(stopwords_file, "r", encoding="utf-8") as fin:
        for line in fin:
            word = line.rstrip("\n")
            stopwords.append(word)
    return stopwords


def load_word2vec_pretrained(glove_file: str):
    """
    load pretrained word2vec embedding from GloVe
    """
    dirname, basename = os.path.split(glove_file)
    prefix = ".".join(basename.split(".")[:-1])
    word2vec_savefile = os.path.join(dirname, prefix + ".word2vec.pkl")
    if os.path.isfile(word2vec_savefile):
        word2vec = pickle.load(open(word2vec_savefile, "rb"))
        word2idx, pretrained_embedding = word2vec["word2idx"], word2vec["embedding"]
        return word2idx, pretrained_embedding

    word2idx = OrderedDict()
    pretrained_embedding = []
    with open(glove_file, "r", encoding="utf-8") as fin:
        for idx, line in enumerate(fin):
            splited_line = line.strip().split()
            word, vector = splited_line[0], splited_line[1:]
            vector = [float(num) for num in vector]
            word2idx[word] = idx
            pretrained_embedding.append(vector)
        pretrained_embedding = np.array(pretrained_embedding, dtype=np.float32)
    word2vec = {"word2idx": word2idx, "embedding": pretrained_embedding}
    pickle.dump(word2vec, open(word2vec_savefile, "wb"))
    return word2idx, pretrained_embedding


def tokenize_and_pad(subtitles: str, stopwords: list, word2idx: dict, pad_word: str, max_seq_len: int):
    """
    tokenize subtitles & embedding words & padding to max_seq_len
    """
    # tokenize
    subtitles = [list(tokenize(subtitle, lowercase=True, deacc=True)) for subtitle in subtitles]
    # get rid of stopwords & embedding words
    subtitles = [[word2idx.get(word, word2idx[pad_word]) for word in subtitle if word not in stopwords] for subtitle in subtitles]
    # lens must between [1, max_seq_len]
    # if there exists some subtitle which length is equal to 0, let <unk> as its only word.
    lens = [min(len(subtitle), max_seq_len) for subtitle in subtitles]
    for idx, length in enumerate(lens):
        if length >= max_seq_len:
            subtitles[idx] = subtitles[idx][:max_seq_len]
        else:
            subtitles[idx] = subtitles[idx] + [word2idx[pad_word] for _ in range(max_seq_len - length)]
        lens[idx] = max(lens[idx], 1)
    return subtitles, lens


def load_khan_data_by_id(filepath: str,
                         word2idx: dict,
                         stopwords: list,
                         max_seq_len: int,
                         pad_word: str):
    """
    load data from `*.keyframes.pkl` which are generated by `utils/sample_keyframe.py`

    load single sample file, extract images, subtitles and finish embedding at the same time.
    """
    if pad_word not in word2idx:
        raise KeyError("'{0}' is not in word2idx!".format(pad_word))

    images, subtitles, lens = [], [], []
    data = pickle.load(open(filepath, "rb"))
    images, subtitles = data["keyframes"], data["subtitles"]
    lens = []
    for idx, section_subtitles in enumerate(subtitles):
        section_subtitles, section_lens = tokenize_and_pad(section_subtitles, stopwords, word2idx, max_seq_len=max_seq_len, pad_word=pad_word)
        subtitles[idx] = section_subtitles
        lens.append(section_lens)
    return images, subtitles, lens


def iter_batch_data(batch: dict, max_item_num: int):
    """
    
    """
    images, subtitles, lens, labels, segments = batch["images"], batch["subtitles"], batch["lens"], batch["labels"], batch["segments"]
    image_segments = batch["image_segments"]
    mini_batch = {"images": [], "subtitles": [], "lens": [], "labels": [], "segments": [], "image_segments": []}
    segment_num_per_video = [sum(segments[idx]) for idx in range(len(segments))]
    image_num_per_video = [sum(image_segments[idx]) for idx in range(len(image_segments))]
    index = 0
    while index < len(segments):
    # for idx, segment in enumerate(segments):
        curr_item_num = 0
        while index < len(segment_num_per_video) \
            and (curr_item_num + segment_num_per_video[index] <= max_item_num \
                or (curr_item_num == 0 and segment_num_per_video[index] > max_item_num)):      # 如果单个 video 的 segment 数量大于 max_item_num 则强行塞进去
            start_idx = sum(segment_num_per_video[:index])
            end_idx = sum(segment_num_per_video[:index + 1])
            image_start_idx = sum(image_num_per_video[:index])
            image_end_idx = sum(image_num_per_video[:index + 1])
            mini_batch["images"].append(images[image_start_idx:image_end_idx])
            mini_batch["subtitles"].append(subtitles[start_idx:end_idx])
            mini_batch["lens"].append(lens[start_idx:end_idx])
            mini_batch["labels"].append(labels[index])
            mini_batch["segments"].append(segments[index])
            mini_batch["image_segments"].append(image_segments[index])
            curr_item_num += segment_num_per_video[index]
            index += 1
        mini_batch["images"] = torch.cat(mini_batch["images"], dim=0)
        mini_batch["subtitles"] = torch.cat(mini_batch["subtitles"], dim=0)
        mini_batch["lens"] = torch.cat(mini_batch["lens"], dim=0)
        mini_batch["labels"] = torch.stack(mini_batch["labels"], dim=0)

        yield mini_batch
        mini_batch = {"images": [], "subtitles": [], "lens": [], "labels": [], "segments": [], "image_segments": []}


def get_labels_by_threshold(scores: np.ndarray, index2know: dict, threshold: float, offset: int=0):
    """
    get predicted label idices & names according to scores and threshold

    offset for get_hierarchy_labels_by_threshold(), default to 0
    """
    predict_labels = (scores >= threshold).astype(np.int32)
    predict_labels_indices = np.argsort(predict_labels, axis=1)[:, ::-1]
    batch_size = scores.shape[0]
    labels_indices = [sorted((predict_labels_indices[idx][:np.sum(predict_labels[idx])] + offset).tolist()) for idx in range(batch_size)]
    labels_names = [[index2know[index] for index in indices] for indices in labels_indices]
    return labels_indices, labels_names


def get_labels_by_topK(scores: np.ndarray, index2know: dict, topK: int, offset: int=0):
    """
    get predicted label idices & names according to scores and topK

    offset for get_hierarchy_labels_by_topK(), default to 0
    """
    assert topK > 0, "topK MUST greater than 0!"
    predict_labels_indices = np.argsort(scores, axis=1)[:, ::-1]
    batch_size = scores.shape[0]
    labels_indices = [sorted((predict_labels_indices[idx][:topK] + offset).tolist()) for idx in range(batch_size)]
    labels_names = [[index2know[index] for index in indices] for indices in labels_indices]
    return labels_indices, labels_names


def get_hierarchy_labels_by_threshold(scores: np.ndarray, index2know: dict, num_classes_list: list, threshold: float):
    """
    get predicted label idices & names according to scores and threshold
    """
    predict_labels = (scores >= threshold).astype(np.int32)
    start_idx, end_idx = 0, 0
    hierarchy_indices, hierarchy_labels = {}, {}
    for level, classes in enumerate(num_classes_list):
        start_idx = end_idx
        end_idx += classes
        level_indices, level_labels = get_labels_by_threshold(predict_labels[:, start_idx:end_idx],
                                                              index2know=index2know,
                                                              threshold=threshold,
                                                              offset=start_idx)
        hierarchy_indices[level] = level_indices
        hierarchy_labels[level] = level_labels
    return hierarchy_indices, hierarchy_labels


def get_hierarchy_labels_by_topK(scores: np.ndarray, index2know: dict, topK: int):
    """
    get predicted label idices & names according to scores and topK
    """
    assert topK > 0, "topK MUST greater than 0!"
    predict_labels_indices = np.argsort(scores, axis=1)[:, ::-1]
    batch_size = scores.shape[0]
    labels_indices = [sorted(predict_labels_indices[idx][:topK].tolist()) for idx in range(batch_size)]
    labels_names = [[index2know[index] for index in indices] for indices in labels_indices]
    return labels_indices, labels_names


def metric(predicts: np.ndarray, labels: np.ndarray, threshold: float, num_classes_list: list):
    """
    不考虑层级结构的 metric

    return TP, FP, FN
    """
    predict_labels = (predicts >= threshold).astype(np.float32)
    TP = np.sum(predict_labels * labels)
    FP_matrix = ((predict_labels - labels) > 0).astype(np.float32)
    FP = np.sum(FP_matrix)
    FN_matrix = ((labels - predict_labels) > 0).astype(np.float32)
    FN = np.sum(FN_matrix)
    return TP, FP, FN


def calculate(TP: int, FP: int, FN: int):
    """
    return precition, recall, f1
    """
    precision = TP / (TP + FP)
    recall = TP / (TP + FN)
    f1 = 0.0
    if (precision + recall) > 0:
        f1 = 2 * precision * recall / (precision + recall)
    return precision, recall, f1
