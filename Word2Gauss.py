import numpy as np
import theano
import theano.tensor as T
from itertools import islice
import re
from theano import function
import Vocabulary

LARGEST_UINT32 = 4294967295
DTYPE = np.float32




class GaussianDistribution(object):
    def __init__(self, N, size=100, mu0=0.1, sigma_mean0=10, sigma_std0=1.0, sigma_min=0.1, sigma_max=10):
        self.N = N
        self.K = size

        # Parameter initialization

        # mu = random normal with std mu0,mean 0
        self.mu = mu0 * np.random.randn(self.N, self.K).astype(DTYPE)

        # Sigma = random normal with mean sigma_mean0, std sigma_std0, and min/max of sigma_min, sigma_max
        self.Sigma = np.random.randn(self.N, 1).astype(DTYPE)
        self.Sigma *= sigma_std0
        self.Sigma += sigma_mean0
        self.Sigma = np.maximum(sigma_min, np.minimum(self.Sigma, sigma_max))
        self.Gaussian = np.concatenate((self.mu, self.Sigma), axis=1)

    def energy(self, i, j):
        # TensorVariables for mi, mj, si, sj respectivelly.
        a, b = T.fvectors('a', 'b')
        c, d = T.fscalars('c', 'd')

        # Energy as a TensorVariable
        E = -0.5 * (self.K * d / c + T.sum((a - b) ** 2 / c) - self.K - self.K * T.log(d / c))
        enrg = function([a, b, c, d], E)
        return float(enrg(self.mu[i], self.mu[j], float(self.Sigma[i]), float(self.Sigma[j])))

    def gradient(self, i, j):
        grad = np.empty((2, self.K + 1), dtype=DTYPE)

        # TensorVariables for mi, mj, si, sj respectivelly.
        a, b = T.fvectors('a', 'b')
        c, d = T.fscalars('c', 'd')

        # Energy as a TensorVariable
        E = -0.5 * (self.K * d / c + T.sum((a - b) ** 2 / c) - self.K - self.K * T.log(d / c))

        g1 = T.grad(E, a)  # dE/dmi
        f1 = function([a, b, c, d], g1)

        g2 = T.grad(E, b)  # dE/dmj
        f2 = function([a, b, c, d], g2)

        g3 = T.grad(E, c)  # dE/dsi
        f3 = function([a, b, c, d], g3)

        g4 = T.grad(E, d)  # dE/dsj
        f4 = function([a, b, c, d], g4)

        grad[0][:-1] = f1(self.mu[i], self.mu[j], float(self.Sigma[i]), float(self.Sigma[j]))
        grad[1][:-1] = f2(self.mu[i], self.mu[j], float(self.Sigma[i]), float(self.Sigma[j]))
        grad[0, -1] = f3(self.mu[i], self.mu[j], float(self.Sigma[i]), float(self.Sigma[j]))
        grad[1, -1] = f4(self.mu[i], self.mu[j], float(self.Sigma[i]), float(self.Sigma[j]))

        return grad


class GaussianEmbedding(object):
    def __init__(self, N, size=100, covariance_type='spherical',
                 energy='KL', C=1.0, m=0.1, M=10.0, Closs=1.0, eta=1.0):
        self.dist = GaussianDistribution(N, size, 0.1, M, 1.0, m, M)
        self.eta = eta

        self._acc_grad_mu = np.zeros(N)
        self._acc_grad_sigma = np.zeros(N)
        self.C = C
        self.m = m
        self.M = M
        self.Closs = Closs
        self.grad_mu = theano.shared(np.zeros_like(self.dist.mu))
        self.grad_sigma = theano.shared(np.zeros_like(self.dist.Sigma))

        # def loss(self, pos, neg):
        #   return max(0.0,
        #             self.Closs - self.energy.energy(*pos) + self.energy.energy(*neg)
        #            )

    def loss(self, posEng, negEng):
        return max(
            0.0,
            self.Closs - posEng + negEng
        )

    def train(self, pairs):
        # pairs : (i_pos,j_pos) (i_neg,j_neg). comes from text_to_pairs
        posFac = -1.0
        negFac = 1.0
        for pos, neg in pairs:

            # if loss for this case is 0, there's nothing to update
            if self.loss(self.dist.energy(*pos), self.dist.energy(*neg)) < 1e-14:
                continue

            # update positive samples
            posGrad = self.dist.gradient(*pos)
            self.update(posGrad[0], self.eta, posFac, pos[0])
            self.update(posGrad[1], self.eta, posFac, pos[1])

            # update negative samples
            negGrad = self.dist.gradient(*neg)
            self.update(negGrad[0], self.eta, negFac, neg[0])
            self.update(negGrad[1], self.eta, negFac, neg[1])

    def update(self, gradients, eta, fac, k):
        # accumulate mu
        val = self._acc_grad_mu[k]
        val += np.sum(gradients[:-1] ** 2) / len(gradients[:-1])
        self._acc_grad_mu[k] = val

        # val = self.acc_grad_mu[k].get_value()
        # val += np.sum(gradients[:-1] ** 2) / len(gradients[:-1])
        # self.acc_mu_grad_mu[k].set_value(val)

        # accumulate sigma
        val = self._acc_grad_sigma[k]
        val += gradients[-1] ** 2
        self._acc_grad_sigma[k] = val

        # val = self._acc_grad_sigma.get_value()
        # val += gradients[-1] ** 2
        # self._acc_grad_sigma.set_value(val)

        # updates
        # update mu
        val = self.grad_mu[k]
        eta_mu = eta / np.sqrt(self._acc_grad_mu[k] + 1.0)
        updates1 = (self.grad_mu, T.set_subtensor(val, val - (fac * eta_mu * gradients[:-1])))
        updateFunc1 = function([], updates=[updates1])
        updateFunc1()
        # regularization
        new_val = self.grad_mu[k]
        l2_mu = np.sqrt(np.sum(new_val.eval() ** 2))
        if l2_mu > self.C:
            updates2 = (self.grad_mu, T.set_subtensor(new_val, new_val * (self.C / l2_mu)))
            updateFunc2 = function([], updates=[updates2])
            updateFunc2()

            # val = self.grad_mu[k].get_value()
            # val -= fac * eta_mu * gradients[:-1]
            # self.grad_mu[k].set_value(val)
            # l2_mu = np.sqrt(np.sum(self.grad_mu[k].get_value() ** 2))
            # if l2_mu > self.C:
            #   val = self.grad_mu[k].get_value()
            #  val *= (self.C / l2_mu)
            # self.grad_mu[k].set_value(val)

        # update sigma
        val = self.grad_sigma[k]
        eta_sigma = eta / np.sqrt(self._acc_grad_sigma[k] + 1.0)
        updates1 = (self.grad_sigma, T.set_subtensor(val, val - (fac * eta_sigma * gradients[-1])))
        updateFunc1 = function([], updates=[updates1])
        updateFunc1()
        # regularization
        new_val = self.grad_sigma[k]
        updates2 = (self.grad_sigma, T.set_subtensor(new_val, T.maximum(
            float(self.m), T.minimum(float(self.M, new_val))
        )))
        updateFunc2 = function([], updates=[updates2])
        updateFunc2()

        # val = self.grad_sigma[k].get_value()
        # eta_sigma = eta / np.sqrt(val + 1.0)
        # val -= fac * eta * gradients[-1]
        # self.grad_sigma[k].set_value(val)
        # self.grad_sigma[k].set_value(np.maximum(self.m, np.minimum(self.M, val)))


if __name__ == "__main__":
    # change corpus and test path
    corpus = '/media/ralvi/0A527FA0527F8F67/Project/test'
    vocab = Vocabulary(corpus)
    print(vocab.numberOfTokens())
    embeddings = GaussianEmbedding(vocab.numberOfTokens())

    # generate the pairs
    with open('/media/ralvi/0A527FA0527F8F67/Project/test', 'r') as file:
        pairs = vocab.iter_pairs(file)
        print(pairs)
        for pair in pairs:
            print(pair)
