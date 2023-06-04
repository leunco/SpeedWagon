import datasets
import transformers
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import numpy as np
import itertools
import re
import torch
from rouge import Rouge
from transformers import (
    AutoModelForSeq2SeqLM,
    AutoTokenizer,
    Seq2SeqTrainingArguments,
    Seq2SeqTrainer,
    DataCollatorForSeq2Seq,
    TrainingArguments,
    DataCollatorForLanguageModeling,
    EarlyStoppingCallback

)
from datasets import Dataset
from tqdm import tqdm
import glob
import json
import os

import optuna

transformers.__version__ # 4.25.1에 맞추기

train = pd.read_csv('/proj/SpeedWagon/data/train_new_4.csv')
valid = pd.read_csv('/proj/SpeedWagon/data/valid_new_4.csv')

train['Topic'].unique()

def preprocess_sentence(sentence):
    sentence = sentence.lower() # 텍스트 소문자화
    sentence = re.sub(r'[ㄱ-ㅎㅏ-ㅣ]+[/ㄱ-ㅎㅏ-ㅣ]', '', sentence) # 여러개 자음과 모음을 삭제한다.
    sentence = re.sub("[^가-힣a-z0-9#@,-]", " ", sentence) # 영어 외 문자(숫자, 특수문자 등) 공백으로 변환
    sentence = re.sub(r'[" "]+', " ", sentence) # 여러개 공백을 하나의 공백으로 바꿉니다.
    sentence = sentence.strip() # 문장 양쪽 공백 제거
    
    return sentence

def data_process(data):
  # 전체 Text 데이터에 대한 전처리 (1)
  text = []

  for data_text in tqdm(data):
    text.append(preprocess_sentence(data_text))
  
  return text

train_texts = data_process(train['Text'])
val_texts = data_process(valid['Text'])

train_df = pd.DataFrame(zip(train_texts,train['Summary']), columns=['Text', 'Summary'])
val_df = pd.DataFrame(zip(val_texts,valid['Summary']), columns=['Text', 'Summary'])

# DF > data Set으로 전환
train_data = Dataset.from_pandas(train_df) 
val_data = Dataset.from_pandas(val_df)
test_samples = Dataset.from_pandas(val_df)

print(train_data)
print(val_data)
print(test_samples)

#model_checkpoints = "/content/drive/MyDrive/인공지능/생성요약프로젝트/Model/KoBART/checkpoint/domain_adaptation/checkpoint-12500"

# https://huggingface.co/gogamza/kobart-base-v2
# gogamza/kobart-base-v2
model_checkpoints = 'jx7789/kobart_summary_v3'

tokenizer = AutoTokenizer.from_pretrained(model_checkpoints)
model = AutoModelForSeq2SeqLM.from_pretrained(model_checkpoints)

# special_words = [
#                 "#@주소#", "#@이모티콘#", "#@이름#", "#@URL#", "#@소속#",
#                 "#@기타#", "#@전번#", "#@계정#", "#@url#", "#@번호#", "#@금융#", "#@신원#",
#                 "#@장소#", "#@시스템#사진#", "#@시스템#동영상#", "#@시스템#기타#", "#@시스템#검색#",
#                 "#@시스템#지도#", "#@시스템#삭제#", "#@시스템#파일#", "#@시스템#송금#", "#@시스템#",
#                 "#개인 및 관계#", "#미용과 건강#", "#상거래(쇼핑)#", "#시사/교육#", "#식음료#", 
#                 "#여가 생활#", "#일과 직업#", "#주거와 생활#", "#행사#","[sep]"
#                 ]

# tokenizer.add_special_tokens({"additional_special_tokens": special_words})
# model.resize_token_embeddings(len(tokenizer))

# t_len = [len(tokenizer.encode(s)) for s in tqdm(train_df['Text'])]
# s_len = [len(tokenizer.encode(s)) for s in tqdm(train_df['Summary'])]

# fig, axes = plt.subplots(1, 2, figsize=(10, 3.5), sharey=True)
# axes[0].hist(t_len, bins=50, color="C0", edgecolor="C0")
# axes[0].set_title("Dialogue Token Length")
# axes[0].set_xlabel("Length")
# axes[0].set_ylabel("Count")
# axes[1].hist(s_len, bins=50, color="C0", edgecolor="C0")
# axes[1].set_title("Summary Token Length")
# axes[1].set_xlabel("Length")
# plt.tight_layout()
# plt.show()

max_input = 256
max_target = 64
ignore_index = -100# tokenizer.pad_token_id


device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

def add_ignored_data(inputs, max_len, ignore_index):
  if len(inputs) < max_len:
      pad = [ignore_index] *(max_len - len(inputs)) # ignore_index즉 -100으로 패딩을 만들 것인데 max_len - lne(inpu)
      inputs = np.concatenate([inputs, pad])
  else:
      inputs = inputs[:max_len]

  return inputs

def add_padding_data(inputs, max_len):
    pad_index = tokenizer.pad_token_id
    if len(inputs) < max_len:
        pad = [pad_index] *(max_len - len(inputs))
        inputs = np.concatenate([inputs, pad])
    else:
        inputs = inputs[:max_len]

    return inputs 

def preprocess_data(data_to_process):
    label_id= []
    label_ids = []
    dec_input_ids = []
    input_ids = []
    bos = tokenizer('')['input_ids']
    for i in range(len(data_to_process['Text'])):
        input_ids.append(add_padding_data(tokenizer.encode(data_to_process['Text'][i], add_special_tokens=False), max_input))
    for i in range(len(data_to_process['Summary'])):
        label_id.append(tokenizer.encode(data_to_process['Summary'][i]))  
        label_id[i].append(tokenizer.eos_token_id)   
        dec_input_id = bos
        dec_input_id += label_id[i][:-1]
        dec_input_ids.append(add_padding_data(dec_input_id, max_target))  
    for i in range(len(data_to_process['Summary'])):
        label_ids.append(add_ignored_data(label_id[i], max_target, ignore_index))
   
    return {'input_ids': input_ids,
            'attention_mask' : (np.array(input_ids) != tokenizer.pad_token_id).astype(int),
            'decoder_input_ids': dec_input_ids,
            'decoder_attention_mask': (np.array(dec_input_ids) != tokenizer.pad_token_id).astype(int),
            'labels': label_ids}

train_tokenize_data = train_data.map(preprocess_data, batched = True, remove_columns=['Text', 'Summary'])
val_tokenize_data = val_data.map(preprocess_data, batched = True, remove_columns=['Text', 'Summary'])

rouge = Rouge()

def compute_metrics(pred):
    labels_ids = pred.label_ids
    pred_ids = pred.predictions
    pred_str = tokenizer.batch_decode(pred_ids, skip_special_tokens=True)
    labels_ids[labels_ids == -100] = tokenizer.pad_token_id
    label_str = tokenizer.batch_decode(labels_ids, skip_special_tokens=True)
    
    return rouge.get_scores(pred_str, label_str, avg=True) 

training_args = Seq2SeqTrainingArguments(
    ##output_dir="/content/drive/MyDrive/인공지능/생성요약프로젝트/Model/KoBART/checkpoint2/KoBART_Summary_v3",
    output_dir='../results',
    num_train_epochs=5,  # demo
    do_train=True,
    do_eval=True,
    per_device_train_batch_size=128,  # demo
    per_device_eval_batch_size=256,
    learning_rate=3e-05,
    weight_decay=0.1,
    #label_smoothing_factor=0.1,
    predict_with_generate=True, # 생성기능을 사용하고 싶다고 지정한다.
    ##logging_dir="/content/drive/MyDrive/인공지능/생성요약프로젝트/Model/KoBART/logs2",
    logging_dir='../logs',
    save_total_limit=3,
    load_best_model_at_end = True,
    logging_strategy = 'epoch',
    evaluation_strategy  = 'epoch',
    save_strategy ='epoch',
    gpus=2
)

data_collator = DataCollatorForSeq2Seq(tokenizer, model=model) # 데이터 일괄 처리? 

trainer = Seq2SeqTrainer(
    model, 
    training_args,
    train_dataset=train_tokenize_data,
    eval_dataset=val_tokenize_data,
    data_collator=data_collator,
    tokenizer=tokenizer,
    compute_metrics=compute_metrics,
    #callbacks = [EarlyStoppingCallback(early_stopping_patience=2)]
)

trainer.train()

### optuna skeletion
def objective(trial):
    for step in range(100):
        ### trainer.train()
        intermediate_value = rouge.get_scores(summaries_after_tuning, test_samples["Summary"], avg=True)
        trial.report(intermediate_value, step=step)
        if trial.should_prune():
            raise optuna.TrialPruned()

    return rouge.get_scores(summaries_after_tuning, test_samples["Summary"], avg=True)

study = optuna.create_study(direction="maximize")
study.optimize(objective, n_trials=3)
print(study.best_trial.params)

def generate_summary(test_samples, model):

    inputs = tokenizer(
        test_samples["Text"],
        padding="max_length",
        truncation=True,
        max_length=max_target,
        return_tensors="pt",
    )
    input_ids = inputs.input_ids.to(model.device)

    attention_mask = inputs.attention_mask.to(model.device)
    outputs = model.generate(input_ids, num_beams=5, no_repeat_ngram_size=3,
                            attention_mask=attention_mask, 
                            pad_token_id=tokenizer.pad_token_id,
                            bos_token_id=tokenizer.bos_token_id,
                            eos_token_id=tokenizer.eos_token_id,)
    output_str = tokenizer.batch_decode(outputs, skip_special_tokens=True)
    return outputs, output_str

summaries_after_tuning=[]
for test_sample in tqdm(test_samples):
    summaries_after_tuning.append(generate_summary(test_sample, model)[1])
summaries_after_tuning = list(itertools.chain(*summaries_after_tuning))

score = rouge.get_scores(summaries_after_tuning, test_samples["Summary"], avg=True)

for i in range(0, len(summaries_after_tuning), 1000):
    print('idx_{} '.format(i))
    print("Summary after /n"+ summaries_after_tuning[i])
    print("")
    print("Target summary /n"+ test_samples["Summary"][i])
    print("")
    print('Text'+ test_samples["Text"][i])
    print("")
    print(score)
    print('-'*100)
    print("") 
