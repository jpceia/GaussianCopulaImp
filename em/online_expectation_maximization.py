from transforms.online_transform_function import OnlineTransformFunction
from scipy.stats import norm, truncnorm
import numpy as np
from concurrent.futures import ProcessPoolExecutor
from em.expectation_maximization import ExpectationMaximization

def _batch_em_step_body_(args):
    """
    Does a step of the EM algorithm, needed to dereference args to support parallelism
    """
    return _batch_em_step_body(*args)

def _batch_em_step_body(Z, r_lower, r_upper, sigma, num_ord_updates):
    """
    Iterate the rows over provided matrix 
    """
    num, p = Z.shape
    Z_imp = np.copy(Z)
    C = np.zeros((p,p))
    for i in range(num):
        c, z_imp, z = _batch_em_step_body_row(Z[i,:], r_lower[i,:], r_upper[i,:], sigma, num_ord_updates)
        Z_imp[i,:] = z_imp
        Z[i,:] = z
        C += c
    return C, Z_imp, Z

def _batch_em_step_body_row(Z_row, r_lower_row, r_upper_row, sigma, num_ord_updates):
    """
    The body of the em algorithm for each row
    Returns a new latent row, latent imputed row and C matrix, which, when added
    to the empirical covariance gives the expected covariance
    Args:
        Z_row (array): (potentially missing) latent entries for one data point
        r_lower_row (array): (potentially missing) lower range of ordinal entries for one data point
        r_upper_row (array): (potentially missing) upper range of ordinal entries for one data point
        sigma (matrix): estimate of covariance
        num_ord (int): the number of ordinal columns
        num_ord_updates (int): number of times to estimate ordinal mean
    Returns:
        C (matrix): results in the updated covariance when added to the empircal covariance
        Z_imp_row (array): Z_row with latent ordinals updated and missing entries imputed 
        Z_row (array): inpute Z_row with latent ordinals updated
    """
    Z_imp_row = np.copy(Z_row)
    p = Z_row.shape[0]
    num_ord = r_upper_row.shape[0]
    C = np.zeros((p,p))
    obs_indices = np.where(~np.isnan(Z_row))[0]
    missing_indices = np.setdiff1d(np.arange(p), obs_indices) ## Use set difference to avoid another searching
    ord_in_obs = np.where(obs_indices < num_ord)[0]
    ord_obs_indices = obs_indices[ord_in_obs]

    # obtain correlation sub-matrices
    # obtain submatrices by indexing a "cartesian-product" of index arrays
    sigma_obs_obs = sigma[np.ix_(obs_indices,obs_indices)]
    sigma_obs_missing = sigma[np.ix_(obs_indices, missing_indices)]
    sigma_missing_missing = sigma[np.ix_(missing_indices, missing_indices)]

    if len(missing_indices) > 0:
        tot_matrix = np.concatenate((np.identity(len(sigma_obs_obs)), sigma_obs_missing), axis=1)
        intermed_matrix = np.linalg.solve(sigma_obs_obs, tot_matrix)
        sigma_obs_obs_inv = intermed_matrix[:, :len(sigma_obs_obs)]
        J_obs_missing = intermed_matrix[:, len(sigma_obs_obs):]
    else:
        sigma_obs_obs_inv = np.linalg.solve(sigma_obs_obs, np.identity(len(sigma_obs_obs)))
    # initialize vector of variances for observed ordinal dimensions
    var_ordinal = np.zeros(p)

    # OBSERVED ORDINAL ELEMENTS
    # when there is an observed ordinal to be imputed and another observed dimension, impute this ordinal
    if len(obs_indices) >= 2 and len(ord_obs_indices) >= 1:
        for update_iter in range(num_ord_updates):
            # used to efficiently compute conditional mean
            sigma_obs_obs_inv_Z_row = np.dot(sigma_obs_obs_inv, Z_row[obs_indices])
            for ind in range(len(ord_obs_indices)):
                j = obs_indices[ind]
                not_j_in_obs = np.setdiff1d(np.arange(len(obs_indices)),ind) 
                v = sigma_obs_obs_inv[:,ind]
                new_var_ij = np.asscalar(1.0/v[ind])
                #new_mean_ij = np.dot(v[not_j_in_obs], Z_row[obs_indices[not_j_in_obs]]) * (-new_var_ij)
                new_mean_ij = Z_row[j] - new_var_ij*sigma_obs_obs_inv_Z_row[ind]
                mean, var = truncnorm.stats(
                    a=(r_lower_row[j] - new_mean_ij) / np.sqrt(new_var_ij),
                    b=(r_upper_row[j] - new_mean_ij) / np.sqrt(new_var_ij),
                    loc=new_mean_ij,
                    scale=np.sqrt(new_var_ij),
                    moments='mv')
                if np.isfinite(var):
                    var_ordinal[j] = var
                    if update_iter == num_ord_updates - 1:
                        C[j,j] = C[j,j] + var 
                if np.isfinite(mean):
                    Z_row[j] = mean

    Z_obs = Z_row[obs_indices]
    Z_imp_row[obs_indices] = Z_obs
    # MISSING ELEMENTS
    if len(missing_indices) > 0:
        #print("J_obs_missing: "+str(J_obs_missing.shape))
        #print("Z_obs: "+str(Z_obs.shape))
        #print("Z_obs nan: "+str(np.sum(np.isnan(Z_obs))))
        #print("Z_obs max: "+str(np.max(Z_obs)))
        #print("Z_obs min: "+str(np.min(Z_obs)))
        Z_imp_row[missing_indices] = np.matmul(J_obs_missing.T,Z_obs)
        # variance expectation and imputation
        if len(ord_obs_indices) >= 1 and len(obs_indices) >= 2 and np.sum(var_ordinal) > 0:
            cov_missing_obs_ord = J_obs_missing[ord_in_obs].T * var_ordinal[ord_obs_indices]
            C[np.ix_(missing_indices, ord_obs_indices)] += cov_missing_obs_ord
            C[np.ix_(ord_obs_indices, missing_indices)] += cov_missing_obs_ord.T
            C[np.ix_(missing_indices, missing_indices)] += sigma_missing_missing - np.matmul(J_obs_missing.T, sigma_obs_missing) + np.matmul(cov_missing_obs_ord, J_obs_missing[ord_in_obs])
        else:
            C[np.ix_(missing_indices, missing_indices)] += sigma_missing_missing - np.matmul(J_obs_missing.T, sigma_obs_missing)
    return C, Z_imp_row, Z_row


class OnlineExpectationMaximization(ExpectationMaximization):
    def __init__(self, cont_indices, ord_indices, window_size=200, sigma_init=None):
        self.transform_function = OnlineTransformFunction(cont_indices, ord_indices, window_size=window_size)
        self.cont_indices = cont_indices
        self.ord_indices = ord_indices
        # we assume boolean array of indices
        p = len(cont_indices)
        # By default, sigma corresponds to the correlation matrix of the permuted dataset (ordinals appear first, then continuous)
        if sigma_init is not None:
            self.sigma = sigma_init
        else:
            self.sigma = np.identity(p)
        # track what iteration the algorithm is on for use in weighting samples
        self.iteration = 1


    def fit_and_predict(self, X, batch_size=50, max_workers=1, num_ord_updates=2, decay_coef=0.5, sigma_update=True, marginal_update=True):
        """
        Updates the fit of the copula using the data in X and returns the 
        imputed values and the new correlation for the copula

        Args:
            X (matrix): data matrix with entries to use to update copula and be imputed
            batch_size (positive int): the size of each batch
            max_workers (positive int): the maximum number of workers for parallelism 
            num_ord_updates (positive int): the number of times to re-estimate the latent ordinals per batch
            decay_coef (float in (0,1)): tunes how much to weight new covariance estimates
        Returns:
            X_imp (matrix): X with missing values imputed
        """
        j = 0
        X_imp = np.zeros(X.shape)
        num_batch = len(X) // batch_size
        while j < num_batch:
            start = j * batch_size
            end = (j+1) * batch_size
            X_batch = np.copy(X[start:end, :])
            X_imp[start:end, :] = partial_fit_and_predict(X_batch, max_workers, num_ord_updates, decay_coef, sigma_update, marginal_update)
            j += 1
        if j * batch_size < len(X):
            start = j * batch_size
            end = len(X)
            X_batch = np.copy(X[start:end, :])
            X_imp[start:end, :] = partial_fit_and_predict(X_batch, max_workers, num_ord_updates, decay_coef, sigma_update, marginal_update)
        return X_imp


    def partial_fit_and_predict(self, X_batch, max_workers=1, num_ord_updates=2, decay_coef=0.5, sigma_update=True, marginal_update = True, sigma_out=False):
        """
        Updates the fit of the copula using the data in X_batch and returns the 
        imputed values and the new correlation for the copula

        Args:
            X_batch (matrix): data matrix with entries to use to update copula and be imputed
            max_workers (positive int): the maximum number of workers for parallelism 
            num_ord_updates (positive int): the number of times to re-estimate the latent ordinals per batch
            decay_coef (float in (0,1)): tunes how much to weight new covariance estimates
        Returns:
            X_imp (matrix): X_batch with missing values imputed
        """
        
        #if not update:
            #old_window = self.transform_function.window
            #old_update_pos = self.transform_function.update_pos
        if marginal_update:
            self.transform_function.partial_fit(X_batch)
        # update marginals with the new batch
        #self.transform_function.partial_fit(X_batch)
        # print("X_batch", X_batch)
        res = self._fit_covariance(X_batch, max_workers, num_ord_updates, decay_coef, sigma_update, sigma_out)
        if sigma_out:
            Z_batch_imp, sigma = res
        else:
            Z_batch_imp = res
        # Rearrange Z_imp so that it's columns correspond to the columns of X
        # print("Z_batch_imp", Z_batch_imp)
        Z_imp_rearranged = np.empty(X_batch.shape)
        Z_imp_rearranged[:,self.ord_indices] = Z_batch_imp[:,:np.sum(self.ord_indices)]
        Z_imp_rearranged[:,self.cont_indices] = Z_batch_imp[:,np.sum(self.ord_indices):]
        X_imp = np.empty(X_batch.shape)
        X_imp[:,self.cont_indices] = self.transform_function.partial_evaluate_cont_observed(Z_imp_rearranged, X_batch)
        X_imp[:,self.ord_indices] = self.transform_function.partial_evaluate_ord_observed(Z_imp_rearranged, X_batch)
        #if not update:
            #self.transform_function.window = old_window
            #self.transform_function.update_pos = old_update_pos 
         #   pass
        if sigma_out:
            return X_imp, sigma
        else:
            return X_imp

    def _fit_covariance(self, X_batch, max_workers=1, num_ord_updates=2, decay_coef=0.5, update=True, sigma_out=False):
        """
        Updates the covariance matrix of the gaussian copula using the data 
        in X_batch and returns the imputed latent values corresponding to 
        entries of X_batch and the new sigma

        Args:
            X_batch (matrix): data matrix with which to update copula and with entries to be imputed
            max_workers: the maximum number of workers for parallelism 
            num_ord_updates: the number of times to restimate the latent ordinals per batch
            decay_coef (float in (0,1)): tunes how much to weight new covariance estimates
        Returns:
            sigma (matrix): an updated estimate of the covariance of the copula
            Z_imp (matrix): estimates of latent values in X_batch
        """
        Z_ord_lower, Z_ord_upper = self.transform_function.partial_evaluate_ord_latent(X_batch) 
        #print("ordinal lower size: "+str(Z_ord_lower.shape))
        #print("all missing: "+str(np.all(np.isnan(Z_ord_lower))))
        Z_ord = self._init_Z_ord(Z_ord_lower, Z_ord_upper)
        Z_cont = self.transform_function.partial_evaluate_cont_latent(X_batch) 
        # Latent variable matrix with columns sorted as ordinal, continuous
        Z = np.concatenate((Z_ord, Z_cont), axis=1)
        batch_size, p = Z.shape
        # track previous sigma for the purpose of early stopping
        prev_sigma = self.sigma
        Z_imp = np.zeros((batch_size, p))
        C = np.zeros((p, p))
        if max_workers==1:
            C, Z_imp, Z = _batch_em_step_body(Z, Z_ord_lower, Z_ord_upper, prev_sigma, num_ord_updates)
        else:
            divide = batch_size/max_workers * np.arange(max_workers+1)
            divide = divide.astype(int)
            args = [(Z[divide[i]:divide[i+1],:], Z_ord_lower[divide[i]:divide[i+1],:], Z_ord_upper[divide[i]:divide[i+1],:], prev_sigma, num_ord_updates) for i in range(max_workers)]
            # divide each batch into max_workers parts instead of n parts
            with ProcessPoolExecutor(max_workers=max_workers) as pool:
                res = pool.map(_batch_em_step_body_, args)
                for i,(C_divide, Z_imp_divide, Z_divide) in enumerate(res):
                    Z_imp[divide[i]:divide[i+1],:] = Z_imp_divide
                    Z[divide[i]:divide[i+1],:] = Z_divide # not necessary if we only do on EM iteration 
                    C += C_divide
        C = C/batch_size
        sigma = np.cov(Z_imp, rowvar=False) + C
        #print("Zimp nan: "+str(np.sum(np.isnan(Z_imp))))
        #print("incremental sigma: ")
        #print("sigma nan: "+str(np.sum(np.isnan(sigma))))
        sigma = self._project_to_correlation(sigma)
        #print("incremental sigma correlation: ")
        #print(sigma)
        if update:
            self.sigma = sigma*decay_coef + (1 - decay_coef)*prev_sigma
            prev_sigma = self.sigma
            self.iteration += 1
        if sigma_out:
            if update:
                sigma = self.get_sigma()
            else:
                sigma = self.get_sigma(sigma*decay_coef + (1 - decay_coef)*prev_sigma)
            return Z_imp, sigma
        else:
            return Z_imp

    def get_sigma(self, sigma=None):
        if sigma is None:
            sigma = self.sigma
        sigma_rearranged = np.empty(sigma.shape)
        sigma_rearranged[np.ix_(self.ord_indices,self.ord_indices)] = sigma[:np.sum(self.ord_indices),:np.sum(self.ord_indices)]
        sigma_rearranged[np.ix_(self.cont_indices,self.cont_indices)] = sigma[np.sum(self.ord_indices):,np.sum(self.ord_indices):]
        sigma_rearranged[np.ix_(self.cont_indices,self.ord_indices)] = sigma[np.sum(self.ord_indices):,:np.sum(self.ord_indices)]
        sigma_rearranged[np.ix_(self.ord_indices,self.cont_indices)] =  sigma_rearranged[np.ix_(self.cont_indices,self.ord_indices)].T
        return sigma_rearranged

    def _init_sigma(self, sigma):
        sigma_new = np.empty(sigma.shape)
        sigma_new[:np.sum(self.ord_indices),:np.sum(self.ord_indices)] = sigma[np.ix_(self.ord_indices,self.ord_indices)]
        sigma_new[np.sum(self.ord_indices):,np.sum(self.ord_indices):] = sigma[np.ix_(self.cont_indices,self.cont_indices)]
        sigma_new[np.sum(self.ord_indices):,:np.sum(self.ord_indices)] = sigma[np.ix_(self.cont_indices,self.ord_indices)] 
        sigma_new[:np.sum(self.ord_indices),np.sum(self.ord_indices):] = sigma[np.ix_(self.ord_indices,self.cont_indices)] 
        self.sigma = sigma_new

    def change_point_test(self, x_batch, decay_coef, nsample=100, max_workers=4):
        n,p = x_batch.shape
        #xsample = np.random.multivariate_normal(np.zeros(p), self.sigma, (nsample,n))
        statistics = np.zeros((nsample,3))
        sigma_old = self.get_sigma()
        _, sigma_new = self.partial_fit_and_predict(x_batch, decay_coef=decay_coef, max_workers=max_workers, marginal_update=True, sigma_update=False, sigma_out=True)
        s = self.get_matrix_diff(sigma_old, sigma_new)
        # generate incomplete mixed data samples
        for i in range(nsample):
            np.random.seed(i)
            z = np.random.multivariate_normal(np.zeros(p), sigma_old, n)
            # mask
            x = np.empty(x_batch.shape)
            x[:,self.cont_indices] = self.transform_function.partial_evaluate_cont_observed(z)
            x[:,self.ord_indices] = self.transform_function.partial_evaluate_ord_observed(z)
            loc = np.isnan(x_batch)
            x[loc] = np.nan
            #xsample[i,:,:] = x
            _, sigma = self.partial_fit_and_predict(x, decay_coef=decay_coef, max_workers=max_workers, marginal_update=False, sigma_update=False, sigma_out=True)
            statistics[i,:] = self.get_matrix_diff(sigma_old, sigma)
            #print("Sigma change after pseudo examples: "+str(self.get_matrix_diff(self.sigma, sigma_old)))
        # compute test statistics
        pval = np.zeros(3)
        for j in range(3):
            pval[j] = np.sum(s[j]<statistics[:,j])/(nsample+1)
        self._init_sigma(sigma_new)
        return pval, s


        # compute test statistics
    def get_matrix_diff(self, sigma_old, sigma_new):
        p = sigma_old.shape[0]
        u, s, vh = np.linalg.svd(sigma_old)
        factor = (u * np.sqrt(1/s) ) @ vh
        diff = factor @ sigma_new @ factor
        _, s, _ = np.linalg.svd(diff)
        return max(abs(s-1)), np.sum(abs(s-1)), np.linalg.norm(diff-np.identity(p))


        

    