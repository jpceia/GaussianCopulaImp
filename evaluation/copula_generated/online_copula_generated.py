import numpy as np
from em.online_expectation_maximization import OnlineExpectationMaximization
from scipy.stats import random_correlation, norm, expon
from evaluation.helpers import *
import time

def generate_sigma():
    W = np.random.normal(size=(15,15))
    covariance = np.matmul(W,W.T)
    D = np.diagonal(covariance)
    D_neg_half = np.diag(1.0/np.sqrt(D))
    return np.matmul(np.matmul(D_neg_half, covariance), D_neg_half)

if __name__ == "__main__":
    scaled_errors = []
    smaes = []
    rmses = []
    runtimes = []
    NUM_RUNS = 10
    for i in range(1,NUM_RUNS+1):
        np.random.seed(i)
        print("starting epoch: " + str(i))
        print("\n\n\n")
        sigma = generate_sigma()
        mean = np.zeros(sigma.shape[0])
        X = np.random.multivariate_normal(mean, sigma, size=2000)
        X[:,:5] = expon.ppf(norm.cdf(X[:,:5]), scale = 3)
        X[:,5] = cont_to_binary(X[:,5])
        X[:,6] = cont_to_binary(X[:,6])
        X[:,7] = cont_to_binary(X[:,7])
        X[:,8] = cont_to_binary(X[:,8])
        X[:,9] = cont_to_binary(X[:,9])
        X[:,10] = cont_to_ord(X[:,10], k=5)
        X[:,11] = cont_to_ord(X[:,11], k=5)
        X[:,12] = cont_to_ord(X[:,12], k=5)
        X[:,13] = cont_to_ord(X[:,13], k=5)
        X[:,14] = cont_to_ord(X[:,14], k=5)
        # mask a given % of entries
        MASK_FRACTION = 0.3
        X_masked, mask_indices = mask(X, MASK_FRACTION)
        cont_indices = np.array([True, True, True, True, True, False, False, False, False, False, False, False, False, False, False])
        ord_indices = np.array([False, False, False, False, False, True, True, True, True, True, True, True, True, True, True])
        oem = OnlineExpectationMaximization(cont_indices, ord_indices)
        start_time = time.time()
        i = 0
        X_imp = np.empty(X_masked.shape)
        BATCH_SIZE=20
        scaled_errors = []
        while i*BATCH_SIZE < X_masked.shape[0]:  
            X_imp[i*BATCH_SIZE:(i+1)*BATCH_SIZE,:], sigma_imp = oem.partial_fit_and_predict(X_masked[i*BATCH_SIZE:(i+1)*BATCH_SIZE,:])
            i +=1 
            print("iteration is: ")
            print(i)
            scaled_error = get_scaled_error(sigma_imp, sigma)
            scaled_errors.append(scaled_error)
        end_time = time.time()
        runtimes.append(end_time - start_time)
        smae = get_smae(X_imp, X, X_masked)
        # update error to be normalized
        rmse = get_scaled_error(X_imp[:,:5], X[:,:5])
        print("correlation error is: ")
        print(scaled_error)
        print("mean absolute errors are: ")
        print(smae)
        print("root mean squared errors are: ")
        print(rmse)
        scaled_errors.append(scaled_error)
        smaes.append(smae)
        rmses.append(rmse)
    print("\n\n")
    print("All scaled errors are: ")
    print(scaled_errors)
    print("mean of scaled errors is: ")
    print(np.mean(np.array(scaled_errors)))
    print("std deviation of scaled errors is: ")
    print(np.std(np.array(scaled_errors)))
    print("\n\n")
    mean_smaes = np.mean(np.array(smaes),axis=0)
    print("mean of smaes is: ")
    print(mean_smaes)
    print("mean cont smaes are: ")
    print(np.mean(mean_smaes[:5]))
    print("mean bin smaes are: ")
    print(np.mean(mean_smaes[5:10]))
    print("mean ord smaes are: ")
    print(np.mean(mean_smaes[10:]))
    std_dev_smaes = np.std(np.array(smaes),axis=0)
    print("std deviation of smaes is: ")
    print(std_dev_smaes)
    print("std dev cont smaes are: ")
    print(np.mean(std_dev_smaes[:5]))
    print("std dev bin smaes are: ")
    print(np.mean(std_dev_smaes[5:10]))
    print("std dev ord smaes are: ")
    print(np.mean(std_dev_smaes[10:]))
    print("\n\n")
    print("All rmses are: ")
    print(rmses)
    print("mean of rmses is: ")
    print(np.mean(np.array(rmses),axis=0))
    print("std deviation of rmses is: ")
    print(np.std(np.array(rmses),axis=0))
    print("all runtimes were: ")
    print(runtimes)
    print("mean time for run is: ")
    print(np.mean(np.array(runtimes)))