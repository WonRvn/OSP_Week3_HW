# -*- coding: utf-8 -*-
"""[Baseline]_FastText + LSTM.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1BHI06XgtD7OFnC5rWe8iplBp8Hwe86_l
"""

!pip install gensim
!pip install tensorflow
!pip install optuna
!pip install seaborn matplotlib
!pip install imbalanced-learn
!pip install contractions

from google.colab import drive
drive.mount('/content/drive')

import pandas as pd
import numpy as np
from gensim.models import FastText
from sklearn.model_selection import train_test_split
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dropout, Dense, Embedding
from tensorflow.keras.preprocessing.sequence import pad_sequences
from tensorflow.keras.preprocessing.text import Tokenizer
from tensorflow.keras.initializers import Constant
import nltk
import re
from nltk.stem import WordNetLemmatizer
from nltk.corpus import stopwords
from sklearn.utils import resample
import seaborn as sns
import matplotlib.pyplot as plt
import contractions

train = pd.read_csv('/content/drive/MyDrive/competition/Court_Judgment/train.csv')
test = pd.read_csv('/content/drive/MyDrive/competition/Court_Judgment/test.csv')

"""## Data Preprocessing w/ FastText"""

(train['first_party_winner'] == 0).sum()

(train['first_party_winner'] == 1).sum()

subset_0 = train[train["first_party_winner"] == 0]
subset_1 = train[train["first_party_winner"] == 1]

subset_1_downsampled = resample(subset_1,
                                replace=False,
                                n_samples=829,
                                random_state=42)

train = pd.concat([subset_0, subset_1_downsampled])

nltk.download('wordnet')
nltk.download('punkt')
nltk.download('stopwords')

lemmatizer = WordNetLemmatizer()

def preprocess_text(text):
    # Convert NaNs to empty strings
    if pd.isnull(text):
        text = ''

    # Expand contractions
    text = contractions.fix(text)

    # Remove punctuation
    text = re.sub(r'[^\w\s]', '', text)

    # Convert text to lowercase
    text = text.lower()

    # Remove words and digits containing digits
    text = re.sub(r'\w*\d\w*', '', text)

    # Remove extra spaces
    text = re.sub(r'\s+', ' ', text)

    # Tokenize the text
    tokens = nltk.word_tokenize(text)

    # Remove stopwords and apply lemmatization
    tokens = [lemmatizer.lemmatize(token) for token in tokens if token not in stopwords.words('english')]

    # Rephrase text (if needed)
    # Example: Replace certain phrases or expressions with their corresponding representations
    # tokens = [rephrase(token) for token in tokens]
    return tokens

train['facts'] = train['facts'].apply(preprocess_text)
train['first_party'] = train['first_party'].apply(preprocess_text)
train['second_party'] = train['second_party'].apply(preprocess_text)

test['facts'] = test['facts'].apply(preprocess_text)
test['first_party'] = test['first_party'].apply(preprocess_text)
test['second_party'] = test['second_party'].apply(preprocess_text)

all_texts = train['facts'].tolist() + train['first_party'].tolist() + train['second_party'].tolist()

train['word_count'] = train['facts'].apply(lambda x: len(str(x).split()))
test['word_count'] = test['facts'].apply(lambda x: len(str(x).split()))

# Visualize the word count distribution
plt.figure(figsize=(10, 6))
plt.hist(train['word_count'], bins=20, edgecolor='black')
plt.xlabel('Word Count')
plt.ylabel('Frequency')
plt.title('Distribution of Word Count')
plt.show()

# We train FastText model on all_texts
fasttext_model = FastText(sentences=all_texts, vector_size=200, window=5, min_count=1, workers=4)

# Define Tokenizer
tokenizer = Tokenizer()
tokenizer.fit_on_texts(all_texts)
word_index = tokenizer.word_index

EMBEDDING_DIM = 200  # this should match the dimensionality of the FastText vectors

# Prepare embedding matrix
embedding_matrix = np.zeros((len(word_index) + 1, EMBEDDING_DIM))
for word, i in word_index.items():
    if word in fasttext_model.wv:
        embedding_vector = fasttext_model.wv[word]
        embedding_matrix[i] = embedding_vector

# Load this into an Embedding layer
# Note that we set trainable=False to prevent the weights from being updated during training.
embedding_layer = Embedding(len(word_index) + 1,
                            EMBEDDING_DIM,
                            embeddings_initializer=Constant(embedding_matrix),
                            trainable=False)

def get_vector(model, texts):
    vectors = []
    for text in texts:
        text_vectors = []
        for word in text:
            if word in model.wv.key_to_index:
                text_vectors.append(model.wv.get_vector(word))
        if len(text_vectors) > 0:
            text_vector = np.mean(text_vectors, axis=0)
            vectors.append(text_vector)
        else:
            vectors.append(np.zeros(model.vector_size))
    return np.array(vectors)

X_train_facts = get_vector(fasttext_model, train['facts'])
X_train_party1 = get_vector(fasttext_model, train['first_party'])
X_train_party2 = get_vector(fasttext_model, train['second_party'])
X_train = np.concatenate([X_train_party1, X_train_party2, X_train_facts], axis=1)
Y_train = train['first_party_winner']

X_test_facts = get_vector(fasttext_model, test['facts'])
X_test_party1 = get_vector(fasttext_model, test['first_party'])
X_test_party2 = get_vector(fasttext_model, test['second_party'])
X_test = np.concatenate([X_test_party1,X_test_party2, X_test_facts], axis=1)

X_train, X_val, Y_train, Y_val = train_test_split(X_train, Y_train, test_size=0.2, random_state=123)

"""## Define Model & Train"""

X_train = X_train.reshape((X_train.shape[0], 1, X_train.shape[1]))
X_test = X_test.reshape((X_test.shape[0], 1, X_test.shape[1]))
X_val = X_val.reshape((X_val.shape[0], 1, X_val.shape[1]))

import optuna
from tensorflow.keras.layers import LSTM
from tensorflow.keras.optimizers import Adam, RMSprop
from tensorflow.keras.callbacks import EarlyStopping

def objective(trial):
    # Define the search space for hyperparameters
    units = trial.suggest_int("units", 32, 128)
    learning_rate = trial.suggest_loguniform("learning_rate", 1e-5, 1e-1)
    dropout_rate = trial.suggest_uniform('dropout_rate', 0.0, 0.5)
    batch_size = trial.suggest_categorical("batch_size", [16, 32])
    optimizer = Adam(learning_rate=learning_rate)

    # Define the model architecture
    model = Sequential()
    model.add(LSTM(units, return_sequences=True, input_shape=(1, X_train.shape[2])))
    model.add(Dropout(dropout_rate))
    model.add(LSTM(units))
    model.add(Dropout(dropout_rate))
    model.add(Dense(1, activation='sigmoid'))

    # Compile the model
    model.compile(optimizer=optimizer, loss='binary_crossentropy', metrics=['accuracy'])

    # Define early stopping
    es = EarlyStopping(monitor='val_loss', mode='min', verbose=1, patience=10)

    # Train the model
    model.fit(X_train, Y_train, epochs=100, batch_size=batch_size, validation_data=(X_val, Y_val), verbose=0, callbacks=[es])

    # Evaluate the model
    accuracy = model.evaluate(X_val, Y_val, verbose=0)[1]

    return accuracy

# Define the study and optimize the objective function
study = optuna.create_study(direction='maximize')
study.optimize(objective, n_trials=50)

# Print the best hyperparameters and objective value
best_params = study.best_params
best_value = study.best_value
print("Best Parameters: ", best_params)
print("Best Value: ", best_value)

from sklearn.metrics import roc_curve

model = Sequential()
model.add(LSTM(best_params['units'], return_sequences=True, input_shape=(1, X_train.shape[2])))
model.add(Dropout(best_params['dropout_rate']))
model.add(LSTM(best_params['units']))
model.add(Dropout(best_params['dropout_rate']))
model.add(Dense(1, activation='sigmoid'))

model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])

es = EarlyStopping(monitor='val_loss', mode='min', verbose=1, patience=10)

# Train the model
model.fit(X_train, Y_train, epochs=100, batch_size=best_params['batch_size'], validation_data=(X_val, Y_val), callbacks=[es])
#model.fit(X_train, Y_train, epochs=100, batch_size=best_params['batch_size'], validation_data=(X_val, Y_val))

vector_size = X_train.shape[2]  # Assuming X_train is already defined
X_test = X_test.reshape((X_test.shape[0], 1, vector_size))

# predicting probabilities instead of classes
pred_probs = model.predict(X_test)

# get the false positive rate, true positive rate, and all thresholds
fpr, tpr, thresholds = roc_curve(Y_val, model.predict(X_val).ravel())

# calculate the g-mean for each threshold
gmeans = np.sqrt(tpr * (1-fpr))

# locate the index of the largest g-mean
ix = np.argmax(gmeans)

print('Best Threshold=%f' % thresholds[ix])

from sklearn.metrics import roc_curve, auc
import matplotlib.pyplot as plt

# Compute ROC curve and ROC area for each class
fpr, tpr, _ = roc_curve(Y_val, model.predict(X_val).ravel())
roc_auc = auc(fpr, tpr)

plt.figure()
lw = 2
plt.plot(fpr, tpr, color='darkorange',
         lw=lw, label='ROC curve (area = %0.2f)' % roc_auc)
plt.plot([0, 1], [0, 1], color='navy', lw=lw, linestyle='--')
plt.xlim([0.0, 1.0])
plt.ylim([0.0, 1.05])
plt.xlabel('False Positive Rate')
plt.ylabel('True Positive Rate')
plt.title('Receiver Operating Characteristic')
plt.legend(loc="lower right")
plt.show()

"""## Inference & Submission"""

predictions = (pred_probs > thresholds[ix]).astype(int).flatten()

submit = pd.read_csv('/content/drive/MyDrive/competition/Court_Judgment/sample_submission.csv')

submit['first_party_winner'] = predictions
submit.to_csv('/content/drive/MyDrive/competition/Court_Judgment/baseline_submit_best.csv', index=False)
print('Done')