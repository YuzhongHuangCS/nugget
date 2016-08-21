import numpy
import time
import sys
import subprocess
import os
import random
import cPickle
import copy

import theano
from theano import tensor as T
from collections import OrderedDict, defaultdict
from theano.tensor.nnet import conv
from theano.tensor.signal import downsample
import theano.tensor.shared_randomstreams
from model import *

#dataset_path = '/home/thn235/projects/extension/ver1/word2vec_transfer.pkl'
dataset_path = '/scratch/thn235/projects/extension/ver1/word2vec_transfer.pkl'

##################################################################

def generateDataInstance(rev, dictionaries, embeddings, features, mLen):

    numAnchor = embeddings['anchor'].shape[0]-1
    numPossibleTypes = len(dictionaries['possibleTypes'])
    numDep = len(dictionaries['dep'])
    
    res = defaultdict(list)
    for id in range(len(rev['word'])):
        for fet in features:
            if fet == 'word':
                if rev['word'][id] not in dictionaries['word']:
                    print 'cannot find id for word: ', rev['word'][id]
                    exit()
                res['word'] += dictionaries['word'][rev['word'][id]]
                continue
            
            if fet == 'anchor':
                anchor = numAnchor / 2 + id - rev['anchor']
                scalar_anchor = anchor+1
                vector_anchor = [0] * numAnchor
                vector_anchor[anchor] = 1
                res['anchor'].append(vector_anchor if features['anchor'] == 1 else scalar_anchor)
                continue
            
            if fet == 'possibleTypes' or fet == 'dep':
                vector_fet = [0] * (numDep if fet == 'dep' else numPossibleTypes)
                for fid in rev[fet][id]:
                    vector_fet[fid] = 1
                res[fet].append(vector_fet)
                continue
            
            numFet = len(dictionaries[fet])-1
            scalar_fet = rev[fet][id]
            vector_fet = [0] * numFet
            if scalar_fet > 0:
                vector_fet[scalar_fet-1] = 1
            res[fet].append(vector_fet if features[fet] == 1 else scalar_fet)
    
    return res

def make_data(revs, dictionaries, embeddings, features):

    mLen = -1
    for datn in revs:
        for doc in revs[datn]:
            for ins in revs[datn][doc]['instances']:
                if len(ins['word']) > mLen:
                    mLen = len(ins['word'])
    
    print 'maximum of length in the dataset: ', mLen
    
    res = {}
    idMappings = {}
    for datn in revs:
        res[datn] = defaultdict(list)
        idMappings[datn] = {}
        iid = -1
        for doc in revs[datn]:
            instanceId = -1
            for rev in revs[datn][doc]['instances']:
                ists = generateDataInstance(rev, dictionaries, embeddings, features, mLen)
                
                for kk in ists: res[datn][kk] += [ists[kk]]
                
                res[datn]['binaryFeatures'] += [rev['binaryFeatures']]
                res[datn]['label'] += [rev['subtype']]
                res[datn]['position'] += [rev['anchor']]
                
                iid += 1
                instanceId += 1
                ikey = datn + ' ' + doc + ' ' + str(instanceId)
                idMappings[datn][iid] = ikey
                res[datn]['id'] += [iid]
    
    return res, idMappings

def makeBinaryDictionary(dat, cutoff=1):
    if cutoff < 0: return None, None
    print '-------creating binary feature dictionary on the training data--------'
    
    bfdCounter = defaultdict(int)
    for rev in dat['binaryFeatures']:
        for fet in rev: bfdCounter[fet] += 1
    print 'binary feature cutoff: ', cutoff
    bfd = {}
    for fet in bfdCounter:
        if bfdCounter[fet] >= cutoff:
            if fet not in bfd: bfd[fet] = len(bfd)
    
    print 'size of dictionary: ', len(bfd)
    
    return bfd

def findMaximumBinaryLength(dats):
    
    maxBiLen = -1
    for corpus in dats:
        for rev in dats[corpus]['binaryFeatures']:
            if len(rev) > maxBiLen: maxBiLen = len(rev)
    print 'maximum number of binary features: ', maxBiLen
    
    return maxBiLen

def convertBinaryFeatures(dat, maxBiLen, bfd):
    if not bfd:
        for corpus in dat: del dat[corpus]['binaryFeatures']
        return -1
    print 'converting binary features to vectors ...'
    for corpus in dat:
        for i in range(len(dat[corpus]['word'])):
            dat[corpus]['binaryFeatures'][i] = getBinaryVector(dat[corpus]['binaryFeatures'][i], maxBiLen, bfd)
            
    return len(bfd)

def getBinaryVector(fets, maxBiLen, dic):
    res = [-1] * (maxBiLen + 1)
    id = 0
    for fet in fets:
        if fet in dic:
            id += 1
            res[id] = dic[fet]
            
    res[0] = id
    return res

def predict(corpus, batch, reModel, idx2word, idx2label, features, task):
    evaluateCorpus = {}
    extra_data_num = -1
    nsen = corpus['word'].shape[0]
    if nsen % batch > 0:
        extra_data_num = batch - nsen % batch
        for ed in corpus:  
            extra_data = corpus[ed][:extra_data_num]
            evaluateCorpus[ed] = numpy.append(corpus[ed],extra_data,axis=0)
    else:
        for ed in corpus: 
            evaluateCorpus[ed] = corpus[ed]
        
    numBatch = evaluateCorpus['word'].shape[0] / batch
    predictions_corpus = numpy.array([], dtype='int32')
    probs_corpus = []
    for i in range(numBatch):
        zippedCorpus = [ evaluateCorpus[ed][i*batch:(i+1)*batch] for ed in features if features[ed] >= 0 ]
        zippedCorpus += [ evaluateCorpus['pos1'][i*batch:(i+1)*batch] ]
        if task == 'relation':
            zippedCorpus += [ evaluateCorpus['pos2'][i*batch:(i+1)*batch] ]
        
        if 'binaryFeatures' in evaluateCorpus:
            zippedCorpus += [ evaluateCorpus['binaryFeatures'][i*batch:(i+1)*batch] ]
        
        clas, probs = reModel.classify(*zippedCorpus)
        predictions_corpus = numpy.append(predictions_corpus, clas)
        probs_corpus.append(probs)
    
    probs_corpus = numpy.concatenate(probs_corpus, axis=0)
    
    if extra_data_num > 0:
        predictions_corpus = predictions_corpus[0:-extra_data_num]
        probs_corpus = probs_corpus[0:-extra_data_num]
    
    groundtruth_corpus = corpus['label']
    
    if predictions_corpus.shape[0] != groundtruth_corpus.shape[0]:
        print 'length not matched!'
        exit()
    #words_corpus = [ map(lambda x: idx2word[x], w) for w in corpus['word']]

    #return predictions_corpus, groundtruth_corpus, words_corpus
    return predictions_corpus, probs_corpus, groundtruth_corpus

def score(predictions, groundtruths):

    zeros = numpy.zeros(predictions.shape, dtype='int')
    numPred = numpy.sum(numpy.not_equal(predictions, zeros))
    numKey = numpy.sum(numpy.not_equal(groundtruths, zeros))
    
    predictedIds = numpy.nonzero(predictions)
    preds_eval = predictions[predictedIds]
    keys_eval = groundtruths[predictedIds]
    correct = numpy.sum(numpy.equal(preds_eval, keys_eval))
    
    #numPred, numKey, correct = 0, 0, 0
    
    precision = 100.0 * correct / numPred if numPred > 0 else 0.0
    recall = 100.0 * correct / numKey if numKey > 0 else 0.0
    f1 = (2.0 * precision * recall) / (precision + recall) if (precision + recall) > 0. else 0.0
    
    return {'p' : precision, 'r' : recall, 'f1' : f1}

def saving(corpus, predictions, probs, groundtruths, idx2word, idx2label, idx2type, address, task):
    
    def determineType(type, pos1, idx2type):
        type1 = type[pos1]
        if type.ndim == 2:
            nty1 = -1
            for i, v in enumerate(type1):
                if v == 1:
                    nty1 = i + 1
                    break
            if nty1 < 0:
                print 'negative type index'
                exit()
            type1 = nty1
        return idx2type[type1]
    
    def generateRelSent(rid, sent, pos1, pos2, type1, type2, pred, gold, idx2word, idx2label):
        res = str(rid) + '\t'
        for i, w in enumerate(sent):
            if w == 0: continue
            w = idx2word[w]
            #w = '_'.join(w.split())
            if i == pos1:
                res += '<ent1-type=' + type1 + '>' + w + '</ent1>' + ' '
            elif i == pos2:
                res += '<ent2-type=' + type2 + '>' + w + '</ent2>' + ' '
            else:
                res += w + ' '
        
        res = res.strip()
        res += '\t' + idx2label[gold] + '\t' + idx2label[pred] + '\t' + ('__TRUE_' if pred == gold else '__FALSE_')
        
        return res
        
    def generateEvtSent(rid, sent, pos, pred, gold, idx2word, idx2label):
        res = str(rid) + '\t'
        for i, w in enumerate(sent):
            if w == 0: continue
            w = idx2word[w]
            #w = '_'.join(w.split())
            if i == pos:
                res += '<anchor>' + w + '</anchor>' + ' '
            else:
                res += w + ' '
        
        res = res.strip()
        res += '\t' + idx2label[gold] + '\t' + idx2label[pred] + '\t' + ('__TRUE_' if pred == gold else '__FALSE_')
        
        return res
    
    def generateProb(rid, pro, gold, idx2label):
        res = str(rid) + '\t'
        for i in range(pro.shape[0]):
            res += idx2label[i] + ':' + str(pro[i]) + ' '
        res = res.strip() + '\t' + idx2label[gold]
        return res
    
    fout = open(address, 'w')
    fprobOut = open(address + '.prob', 'w')
    
    if task == 'relation':
        for rid, sent, pos1, pos2, type, pred, pro, gold in zip(corpus['id'], corpus['word'], corpus['pos1'], corpus['pos2'], corpus['entity'], predictions, probs, groundtruths):
            type1 = determineType(type, pos1, idx2type)
            type2 = determineType(type, pos2, idx2type)
            fout.write(generateRelSent(rid, sent, pos1, pos2, type1, type2, pred, gold, idx2word, idx2label) + '\n')
            fprobOut.write(generateProb(rid, pro, gold, idx2label) + '\n')
    else:
        for rid, sent, pos1, pred, pro, gold in zip(corpus['id'], corpus['word'], corpus['pos1'], predictions, probs, groundtruths):
            fout.write(generateEvtSent(rid, sent, pos1, pred, gold, idx2word, idx2label) + '\n')
            fprobOut.write(generateProb(rid, pro, gold, idx2label) + '\n')
    
    fout.close()
    fprobOut.close()

def generateParameterFileName(model, expected_features, nhidden, conv_feature_map, conv_win_feature_map, multilayerNN1):
    res = model + '.f-'
    for fe in expected_features: res += str(expected_features[fe])
    res += '.h-' + str(nhidden)
    res += '.cf-' + str(conv_feature_map)
    res += '.cwf-'
    for wi in conv_win_feature_map: res += str(wi)
    res += '.mul-'
    for mu in multilayerNN1: res += str(mu)
    res += '.pkl'
    return res

def isWeightConv(conv_win_feature_map, kn):
    for i, conWin in enumerate(conv_win_feature_map):
        if kn.endswith('_win' + str(i) + '_conv_W_' + str(conWin)) and not kn.startswith('_ab_'): return True
    return False

def train(model='basic',
          wedWindow=-1,
          expected_features = OrderedDict([('anchor', -1), ('pos', -1), ('chunk', -1), ('clause', -1), ('possibleTypes', -1), ('dep', -1), ('nonref', -1), ('title', -1), ('eligible', -1)]),
          givenPath=None,
          withEmbs=False, # using word embeddings to initialize the network or not
          updateEmbs=True,
          optimizer='adadelta',
          lr=0.01,
          dropout=0.05,
          regularizer=0.5,
          norm_lim = -1.0,
          verbose=1,
          decay=False,
          batch=50,
          binaryCutoff=1,
          multilayerNN1=[1200, 600],
          multilayerNN2=[1200, 600],
          nhidden=100,
          conv_feature_map=100,
          conv_win_feature_map=[2,3,4,5],
          seed=3435,
          #emb_dimension=300, # dimension of word embedding
          nepochs=50,
          folder='./res'):
    
    folder = '' + folder

    paramFolder = folder + '/params'

    if not os.path.exists(folder): os.mkdir(folder)
    if not os.path.exists(paramFolder): os.mkdir(paramFolder)
    
    paramFileName = paramFolder + '/' + generateParameterFileName(model, expected_features, nhidden, conv_feature_map, conv_win_feature_map, multilayerNN1)

    print 'loading dataset: ', dataset_path, ' ...'
    revs, embeddings, dictionaries = cPickle.load(open(dataset_path, 'rb'))
    
    idx2label = dict((k,v) for v,k in dictionaries['subtype'].iteritems())
    idx2word  = dict((k,v) for v,k in dictionaries['word'].iteritems())

    if not withEmbs:
        wordEmbs = embeddings['randomWord']
    else:
        print 'using word embeddings to initialize the network ...'
        wordEmbs = embeddings['word']
    emb_dimension = wordEmbs.shape[1]
    
    del embeddings['word']
    del embeddings['randomWord']
    embeddings['word'] = wordEmbs
    
    if expected_features['dep'] >= 0: expected_features['dep'] = 1
    if expected_features['possibleTypes'] >= 0: expected_features['possibleTypes'] = 1

    features = OrderedDict([('word', 0)])

    for ffin in expected_features:
        features[ffin] = expected_features[ffin]
        if expected_features[ffin] == 0:
            print 'using features: ', ffin, ' : embeddings'
        elif expected_features[ffin] == 1:
            print 'using features: ', ffin, ' : binary'
        
    datasets, idMappings = make_data(revs, dictionaries, embeddings, features)
    
    dimCorpus = datasets['train']
    
    vocsize = len(idx2word)
    nclasses = len(idx2label)
    nsentences = len(dimCorpus['word'])

    print 'vocabsize = ', vocsize, ', nclasses = ', nclasses, ', nsentences = ', nsentences, ', word embeddings dim = ', emb_dimension
    
    features_dim = OrderedDict([('word', emb_dimension)])
    for ffin in expected_features:
        features_dim[ffin] = ( len(dimCorpus[ffin][0][0]) if (features[ffin] == 1) else embeddings[ffin].shape[1] )
    
    conv_winre = len(dimCorpus['word'][0])
    
    print '------- length of the instances: ', conv_winre
    #binaryFeatureDim = -1
    
    #preparing transfer knowledge
    kGivens = {}
    if givenPath and os.path.exists(givenPath):
        print '****Loading given knowledge in: ', givenPath
        kGivens = cPickle.load(open(givenPath, 'rb'))
    else: print givenPath, ' not exist'
    
    if 'binaryFeatureDict' in kGivens:
        print '********** USING BINARY FEATURE DICTIONARY FROM LOADED MODEL'
        binaryFeatureDict = kGivens['binaryFeatureDict']
    else:
        print '********** CREATING BINARY FEATURE DICTIONARY FROM TRAINING DATA'
        binaryFeatureDict = makeBinaryDictionary(dimCorpus, binaryCutoff)
    maxBinaryFetDim = findMaximumBinaryLength(datasets)
    binaryFeatureDim = convertBinaryFeatures(datasets, maxBinaryFetDim, binaryFeatureDict)
    
    params = {'model' : model,
              'wedWindow' : wedWindow,
              'kGivens' : kGivens,
              'nh' : nhidden,
              'nc' : nclasses,
              'ne' : vocsize,
              'batch' : batch,
              'embs' : embeddings,
              'dropout' : dropout,
              'regularizer': regularizer,
              'norm_lim' : norm_lim,
              'updateEmbs' : updateEmbs,
              'features' : features,
              'features_dim' : features_dim,
              'optimizer' : optimizer,
              'binaryCutoff' : binaryCutoff,
              'binaryFeatureDim' : binaryFeatureDim,
              'binaryFeatureDict' : binaryFeatureDict,
              'multilayerNN1' : multilayerNN1,
              'multilayerNN2' : multilayerNN2,
              'conv_winre' : conv_winre,
              'conv_feature_map' : conv_feature_map,
              'conv_win_feature_map' : conv_win_feature_map}
    
    for corpus in datasets:
        for ed in datasets[corpus]:
            if ed == 'label' or ed == 'id':
                datasets[corpus][ed] = numpy.array(datasets[corpus][ed], dtype='int32')
            else:
                dty = 'float32' if numpy.array(datasets[corpus][ed][0]).ndim == 2 else 'int32'
                datasets[corpus][ed] = numpy.array(datasets[corpus][ed], dtype=dty)
    
    trainCorpus = {} #evaluatingDataset['train']
    augt = datasets['train']
    if nsentences % batch > 0:
        extra_data_num = batch - nsentences % batch
        for ed in augt:
            numpy.random.seed(3435)
            permuted = numpy.random.permutation(augt[ed])   
            extra_data = permuted[:extra_data_num]
            trainCorpus[ed] = numpy.append(augt[ed],extra_data,axis=0)
    else:
        for ed in augt:
            trainCorpus[ed] = augt[ed]
    
    number_batch = trainCorpus['word'].shape[0] / batch
    
    print '... number of batches: ', number_batch
    
    # instanciate the model
    print 'building model ...'
    numpy.random.seed(seed)
    random.seed(seed)
    if model.startswith('#'):
        model = model[1:]
        params['model'] = model
        reModel = eval('hybridModel')(params)
    else: reModel = eval('mainModel')(params)
    print 'done'
    
    evaluatingDataset = OrderedDict([('train', datasets['train']),
                                     ('valid', datasets['valid']),
                                     ('test', datasets['test'])
                                     ])
    
    _predictions, _probs, _groundtruth, _perfs = OrderedDict(), OrderedDict(), OrderedDict(), OrderedDict() #, _words
    
    # training model
    best_f1 = -numpy.inf
    clr = lr
    s = OrderedDict()
    for e in xrange(nepochs):
        s['_ce'] = e
        tic = time.time()
        #nsentences = 5
        print '-------------------training in epoch: ', e, ' -------------------------------------'
        # for i in xrange(nsentences):
        miniId = -1
        for minibatch_index in numpy.random.permutation(range(number_batch)):
            miniId += 1
            trainIn = OrderedDict()
            for ed in features:
                if features[ed] >= 0:
                    if ed not in trainCorpus:
                        print 'cannot find data in train for: ', ed
                        exit()
                    
                    trainIn[ed] = trainCorpus[ed][minibatch_index*batch:(minibatch_index+1)*batch]

            trainPos1 = trainCorpus['pos1'][minibatch_index*batch:(minibatch_index+1)*batch]

            zippedData = [ trainIn[ed] for ed in trainIn ]

            zippedData += [trainPos1]
            
            if task == 'relation':
                trainPos2 = trainCorpus['pos2'][minibatch_index*batch:(minibatch_index+1)*batch]
                zippedData += [trainPos2]
            
            if 'binaryFeatures' in trainCorpus:
                zippedData += [trainCorpus['binaryFeatures'][minibatch_index*batch:(minibatch_index+1)*batch]]

            zippedData += [trainCorpus['label'][minibatch_index*batch:(minibatch_index+1)*batch]]
            
            reModel.f_grad_shared(*zippedData)
            reModel.f_update_param(clr)
            
            for ed in reModel.container['embDict']:
                reModel.container['setZero'][ed](reModel.container['zeroVecs'][ed])
                
            if verbose:
                if miniId % 50 == 0:
                    print 'epoch %i >> %2.2f%%'%(e,(miniId+1)*100./number_batch),'completed in %.2f (sec) <<'%(time.time()-tic)
                    sys.stdout.flush()

        # evaluation // back into the real world : idx -> words
        print 'evaluating in epoch: ', e

        for elu in evaluatingDataset:
            _predictions[elu], _probs[elu], _groundtruth[elu] = predict(evaluatingDataset[elu], batch, reModel, idx2word, idx2label, features, task)
            _perfs[elu] = score(_predictions[elu], _groundtruth[elu])# folder + '/' + elu + '.txt'

        # evaluation // compute the accuracy using conlleval.pl

        #res_train = {'f1':'Not for now', 'p':'Not for now', 'r':'Not for now'}
        perPrint(_perfs)
        
        if _perfs['valid']['f1'] > best_f1:
            #rnn.save(folder)
            best_f1 = _perfs['valid']['f1']
            print '*************NEW BEST: epoch: ', e
            if verbose:
                perPrint(_perfs, len('Current Performance')*'-')

            for elu in evaluatingDataset:
                s[elu] = _perfs[elu]
            s['_be'] = e
            
            print 'saving parameters ...'
            reModel.save(paramFileName)
            print 'saving output ...'
            for elu in evaluatingDataset:
                saving(evaluatingDataset[elu], _predictions[elu], _probs[elu], _groundtruth[elu], idx2word, idx2label, idx2type, folder + '/' + elu + '.best.txt', task)
            #subprocess.call(['mv', folder + '/current.test.txt', folder + '/best.test.txt'])
            #subprocess.call(['mv', folder + '/current.valid.txt', folder + '/best.valid.txt'])
        else:
            print ''
        
        # learning rate decay if no improvement in 10 epochs
        if decay and abs(s['_be']-s['_ce']) >= 10: clr *= 0.5 
        if clr < 1e-5: break

    print '>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>'
    print 'BEST RESULT: epoch: ', s['_be']
    perPrint(s, len('Current Performance')*'-')
    print ' with the model in ', folder

def perPrint(perfs, mess='Current Performance'):
    print '------------------------------%s-----------------------------'%mess
    for elu in perfs:
        if elu.startswith('_'):
            continue
        pri = elu + ' : ' + str(perfs[elu]['p']) + '\t' + str(perfs[elu]['r'])+ '\t' + str(perfs[elu]['f1'])
        print pri
    
    print '------------------------------------------------------------------------------'
    
if __name__ == '__main__':
    pass