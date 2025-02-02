import numpy as np
from scipy.stats import norm, truncnorm

def _em_step_body_(args):
    """
    Does a step of the EM algorithm, needed to dereference args to support parallelism
    """
    return _em_step_body(*args)

def _em_step_body(Z, r_lower, r_upper, sigma, num_ord_updates):
    """
    Iterate the rows over provided matrix 
    """
    num, p = Z.shape
    Z_imp = np.copy(Z)
    C = np.zeros((p,p))
    trunc_warn = False
    for i in range(num):
        c, z_imp, z, warn = _em_step_body_row(Z[i,:], r_lower[i,:], r_upper[i,:], sigma, num_ord_updates)
        Z_imp[i,:] = z_imp
        Z[i,:] = z
        C += c
        trunc_warn = trunc_warn or warn
    # TO DO: no need to return Z, just edit it during the process
    if trunc_warn:
        print('Bad truncated normal stats appear, suggesting the existence of outliers. We skipped the outliers now. More numerically stable version to come...')
    return C, Z_imp, Z


def _em_step_body_row(Z_row, r_lower_row, r_upper_row, sigma, num_ord_updates):
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

    Returns:
        C (matrix): results in the updated covariance when added to the empircal covariance
        Z_imp_row (array): Z_row with latent ordinals updated and missing entries imputed 
        Z_row (array): input Z_row with latent ordinals updated
    """
    Z_imp_row = np.copy(Z_row)
    p = Z_imp_row.shape[0]
    num_ord = r_upper_row.shape[0]
    C = np.zeros((p,p))

    # TO DO: obs_indices = np.argwhere(~np.isnan(x)).flatten()
    obs_indices = np.where(~np.isnan(Z_row))[0] 
    missing_indices = np.setdiff1d(np.arange(p), obs_indices) 
    # TO DO: ord_in_obs = np.argwhere(obs_indices < num_ord).flatten()
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
    truncnorm_warn = False
    if len(obs_indices) >= 2 and len(ord_obs_indices) >= 1:
        for update_iter in range(num_ord_updates):
            # used to efficiently compute conditional mean
            sigma_obs_obs_inv_Z_row = np.dot(sigma_obs_obs_inv, Z_row[obs_indices])
            for ind in range(len(ord_obs_indices)):
                j = obs_indices[ind]
                not_j_in_obs = np.setdiff1d(np.arange(len(obs_indices)),ind) 
                v = sigma_obs_obs_inv[:,ind]
                new_var_ij = 1.0/v[ind]
                new_var_ij = new_var_ij.item()
                new_std_ij = np.sqrt(new_var_ij)
                #new_mean_ij = np.dot(v[not_j_in_obs], Z_row[obs_indices[not_j_in_obs]]) * (-new_var_ij)
                new_mean_ij = Z_row[j] - new_var_ij*sigma_obs_obs_inv_Z_row[ind]
                a_ij, b_ij = (r_lower_row[j] - new_mean_ij) / new_std_ij, (r_upper_row[j] - new_mean_ij) / new_std_ij
                try:
                    mean, var = truncnorm.stats(a=a_ij,b=b_ij,
                        loc=new_mean_ij,
                        scale=new_std_ij,
                        moments='mv')
                    if np.isfinite(var):
                        var_ordinal[j] = var
                        if update_iter == num_ord_updates - 1:
                            C[j,j] = C[j,j] + var 
                    if np.isfinite(mean):
                        Z_row[j] = mean
                except RuntimeWarning:
                    #print(f'Bad truncated normal stats: lower {r_lower_row[j]}, upper {r_upper_row[j]}, a {a_ij}, b {b_ij}, mean {new_mean_ij}, std {new_std_ij}')
                    truncnorm_warn = True
    

    # MISSING ELEMENTS
    Z_obs = Z_row[obs_indices]
    Z_imp_row[obs_indices] = Z_obs
    if len(missing_indices) > 0:
        Z_imp_row[missing_indices] = np.matmul(J_obs_missing.T,Z_obs) 
        # variance expectation and imputation
        if len(ord_obs_indices) >= 1 and len(obs_indices) >= 2 and np.sum(var_ordinal) > 0: 
            cov_missing_obs_ord = J_obs_missing[ord_in_obs].T * var_ordinal[ord_obs_indices]
            C[np.ix_(missing_indices, ord_obs_indices)] += cov_missing_obs_ord
            C[np.ix_(ord_obs_indices, missing_indices)] += cov_missing_obs_ord.T
            C[np.ix_(missing_indices, missing_indices)] += sigma_missing_missing - np.matmul(J_obs_missing.T, sigma_obs_missing) + np.matmul(cov_missing_obs_ord, J_obs_missing[ord_in_obs])
        else:
            C[np.ix_(missing_indices, missing_indices)] += sigma_missing_missing - np.matmul(J_obs_missing.T, sigma_obs_missing)
    return C, Z_imp_row, Z_row, truncnorm_warn