from em.online_expectation_maximization import OnlineExpectationMaximization
from em.batch_expectation_maximization import BatchExpectationMaximization
import numpy as np
from evaluation.helpers import *
import matplotlib.pyplot as plt
import time
from scipy.stats import random_correlation, norm, expon
import pandas as pd

def main(START=1, NUM_RUNS=10):
    NUM_SAMPLES = 10000
    BATCH_SIZE = 40
    WINDOW_SIZE = 200
    NUM_ORD_UPDATES = 2
    NUM_BATCH = int(NUM_SAMPLES*3/BATCH_SIZE)
    smae_online_trials = np.zeros((NUM_RUNS, NUM_BATCH, 3))
    smae_offline_trials = np.zeros((NUM_RUNS, NUM_BATCH, 3))
    for i in range(START, NUM_RUNS+START):
        smae_conts = []
        smae_ords = []
        smae_bins = []
        print("starting epoch: ", i, "\n")
        sigma1 = generate_sigma(3*i-2)
        sigma2 = generate_sigma(3*i-1)
        sigma3 = generate_sigma(3*i)
        mean = np.zeros(sigma1.shape[0])
        X1 = np.random.multivariate_normal(mean, sigma1, size=NUM_SAMPLES)
        X2 = np.random.multivariate_normal(mean, sigma2, size=NUM_SAMPLES)
        X3 = np.random.multivariate_normal(mean, sigma3, size=NUM_SAMPLES)
        X = np.vstack((X1, X2, X3))
        X = np.vstack((X1, X2, X3))
        X[:,:5] = expon.ppf(norm.cdf(X[:,:5]), scale = 3)
        for j in range(5,15,1):
            # 6-10 columns are binary, 11-15 columns are ordinal with 5 levels
            X[:,j] = cont_to_ord(X[:,j], k=2*(j<10)+5*(j>=10))
        cont_indices = np.array([True] * 5 + [False] * 10)
        ord_indices = np.array([False] * 5 + [True] * 10)

        # X_masked = mask_one_per_row(X)
        MASK_NUM = 2
        X_masked, mask_indices = mask_types(X, MASK_NUM, seed=i)
        
        # offline 
        bem = BatchExpectationMaximization() # Switch to batch implementation for acceleration
        start_time = time.time()
        X_imp_offline, _ = bem.impute_missing(X_masked, max_workers=4, batch_c=5, max_iter=2*NUM_BATCH)
        end_time = time.time()
        print("offline time: "+str(end_time-start_time))
        
        # online 
        oem = OnlineExpectationMaximization(cont_indices, ord_indices, window_size=WINDOW_SIZE)
        j = 0
        start_time = time.time()
        X_imp_online = np.zeros(X_masked.shape)
        #print(X_masked.shape, X_imp.shape, X.shape)
        while j<NUM_BATCH:
            start = j*BATCH_SIZE
            end = (j+1)*BATCH_SIZE
            X_masked_batch = np.copy(X_masked[start:end,:])
            X_imp_online[start:end,:] = oem.partial_fit_and_predict(X_masked_batch, 
                                                             max_workers = 4, 
                                                             decay_coef=0.5, 
                                                             num_ord_updates=NUM_ORD_UPDATES)
            # imputation error at each batch
            smae_online_trials[i-1,j,:] = get_smae_per_type(X_imp_online[start:end,:], X[start:end,:], X_masked[start:end,:])
            smae_offline_trials[i-1,j,:] = get_smae_per_type(X_imp_offline[start:end,:], X[start:end,:], X_masked[start:end,:])
            j += 1
        end_time = time.time()
        print("online time: "+str(end_time-start_time))
    
    smae_online= np.mean(smae_online_trials, 0)
    smae_offline= np.mean(smae_offline_trials, 0)
    smae_means = pd.DataFrame(np.concatenate((smae_online, smae_offline), 1))
    smae_means.to_csv("smae_means.csv")
    smae_online= np.std(smae_online_trials, 0)
    smae_offline= np.std(smae_offline_trials, 0)
    smae_stds = pd.DataFrame(np.concatenate((smae_online, smae_offline), 1))
    smae_stds.to_csv("smae_stds.csv")
    
    return smae_means, smae_stds


if __name__ == "__main__":
    smae_means, smae_stds = main(1,10)
    
