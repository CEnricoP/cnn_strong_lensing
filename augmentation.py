"""
Generator that augments data in realtime
"""

import numpy as np
import skimage
import multiprocessing as mp
import time
import glob
import load_data_custom as load_data

###########Parameters

test_path='data/test_data/'
test_data=glob.glob(test_path+'*_r_*.fits')
num_test=len(test_data)

###########

loadsize=100  
NUM_PROCESSES = 2 


CHUNK_SIZE = 25000
IMAGE_WIDTH = 101
IMAGE_HEIGHT = 101             
IMAGE_NUM_CHANNELS = 3

num_sources=load_data.num_sources
num_lenses=load_data.num_lenses
num_neg=load_data.num_neg
num_real_lenses=load_data.num_real_lenses

default_augmentation_params = {
    'zoom_range': (1.0, 1.0),
    'rotation_range': (0, 360),
    'shear_range': (0, 0),
    'translation_range': (-4, 4),
}

## UTILITIES ##

def select_indices(num, num_selected):                      
    selected_indices = np.arange(num)
    np.random.shuffle(selected_indices)
    selected_indices = selected_indices[:num_selected]
    return selected_indices

    
def fast_warp(img, tf, output_shape=(53,53), mode='reflect'):             
    """
    This wrapper function is about five times faster than skimage.transform.warp, for our use case.
    """
    m = tf.params   
    img_wf = np.empty((output_shape[0], output_shape[1], IMAGE_NUM_CHANNELS), dtype='float32')
    for k in range(IMAGE_NUM_CHANNELS):
        img_wf[..., k] = skimage.transform._warps_cy._warp_fast(img[..., k], m, output_shape=output_shape, mode=mode)
    return img_wf

## TRANSFORMATIONS ##

def build_augmentation_transform(zoom=1.0, rotation=0, shear=0, translation=(0, 0)):                
    tform_augment = skimage.transform.AffineTransform(scale=(1/zoom, 1/zoom), rotation=np.deg2rad(rotation), shear=np.deg2rad(shear), translation=translation)
    tform = tform_center + tform_augment + tform_uncenter 
    return tform

def build_ds_transform(ds_factor=1.0, orig_size=(101, 101), target_size=(53, 53), do_shift=True, subpixel_shift=False):
    """
    This version is a bit more 'correct', it mimics the skimage.transform.resize function.
    """

    rows, cols = orig_size
    trows, tcols = target_size
    col_scale = row_scale = ds_factor
    src_corners = np.array([[1, 1], [1, rows], [cols, rows]]) - 1
    dst_corners = np.zeros(src_corners.shape, dtype=np.double)
    dst_corners[:, 0] = col_scale * (src_corners[:, 0] + 0.5) - 0.5
    dst_corners[:, 1] = row_scale * (src_corners[:, 1] + 0.5) - 0.5

    tform_ds = skimage.transform.AffineTransform()
    tform_ds.estimate(src_corners, dst_corners)

    if do_shift:
        if subpixel_shift: 
            cols = (cols // int(ds_factor)) * int(ds_factor)
            rows = (rows // int(ds_factor)) * int(ds_factor)
        shift_x = cols / (2 * ds_factor) - tcols / 2.0
        shift_y = rows / (2 * ds_factor) - trows / 2.0
        tform_shift_ds = skimage.transform.SimilarityTransform(translation=(shift_x, shift_y))
        return tform_shift_ds + tform_ds
    else:
        return tform_ds

center_shift = np.array((IMAGE_HEIGHT, IMAGE_WIDTH)) / 2. - 0.5
tform_center = skimage.transform.SimilarityTransform(translation=-center_shift)
tform_uncenter = skimage.transform.SimilarityTransform(translation=center_shift)
tform_identity = skimage.transform.AffineTransform() # this is an identity transform by default
ds_transforms_default = [tform_identity]
ds_transforms = ds_transforms_default # CHANGE THIS LINE to select downsampling transforms to be used


def random_perturbation_transform(zoom_range, rotation_range, shear_range, translation_range, do_flip=False):   
    
    shift_x = np.random.uniform(*translation_range)
    shift_y = np.random.uniform(*translation_range)
    translation = (shift_x, shift_y)

    # random rotation [0, 360]
    rotation = np.random.uniform(*rotation_range) # there is no post-augmentation, so full rotations here!

    # random shear [0, 5]
    shear = np.random.uniform(*shear_range)

    # # flip
    if do_flip and (np.random.randint(2) > 0): # flip half of the time
        shear += 180
        rotation += 180

    log_zoom_range = [np.log(z) for z in zoom_range]
    zoom = np.exp(np.random.uniform(*log_zoom_range)) # for a zoom factor this sampling approach makes more sense.
    # the range should be multiplicatively symmetric, so [1/1.1, 1.1] instead of [0.9, 1.1] makes more sense.

    return build_augmentation_transform(zoom, rotation, shear, translation)


def perturb_and_dscrop(img, ds_transforms, augmentation_params, target_sizes=None):  
    if target_sizes is None: 
        target_sizes = [(53, 53) for _ in range(len(ds_transforms))]

    tform_augment = random_perturbation_transform(**augmentation_params)

    result = []
    for tform_ds, target_size in zip(ds_transforms, target_sizes):
        result.append(fast_warp(img, tform_ds + tform_augment, output_shape=target_size, mode='reflect').astype('float32'))   #crop here?

    return result

## REALTIME AUGMENTATION GENERATOR ##

def load_and_process_image_source(img_index, ds_transforms, augmentation_params, target_sizes=None):  ##USATA
    img_id = load_data.train_ids_source[img_index]
    img = load_data.load_fits_source(img_id)
    img= np.dstack((img,img,img))
    img_a = perturb_and_dscrop(img, ds_transforms, augmentation_params, target_sizes)
    return img_a
    
def load_and_process_image_lens(img_index, ds_transforms, augmentation_params, target_sizes=None):  ##USATA
    img_id = load_data.train_ids_lens[img_index]
    img = load_data.load_fits_lens(img_id)
    img= np.dstack((img,img,img))
    img_a = perturb_and_dscrop(img, ds_transforms, augmentation_params, target_sizes)
    return img_a

def load_and_process_image_neg(img_index, ds_transforms, augmentation_params, target_sizes=None):  ##USATA
    img_id = load_data.train_ids_neg[img_index]
    img = load_data.load_fits_neg(img_id)
    img= np.dstack((img,img,img))
    img_a = perturb_and_dscrop(img, ds_transforms, augmentation_params, target_sizes)
    return img_a

def load_and_process_image_fixed_test(img_index, ds_transforms, augmentation_transforms, target_sizes=None):
    img_id = test_data[img_index]
    img = load_data.load_fits_test(img_id)
    img= np.dstack((img,img,img))
    return [img]

def load_and_process_image_neg_col(img_index, ds_transforms, augmentation_params, target_sizes=None):  ##USATA
    img_id = load_data.train_ids_neg[img_index]
    img = load_data.load_fits_neg_col(img_id)
    img_a = perturb_and_dscrop(img, ds_transforms, augmentation_params, target_sizes)
    return img_a
    
def load_and_process_image_pos_col(img_index, ds_transforms, augmentation_params, target_sizes=None):  
    img_id_lens = load_data.train_ids_lens[img_index[0]]
    img_id_src = load_data.train_ids_source[img_index[1]]
    img = load_data.load_fits_pos_col(img_id_lens,img_id_src)
    img_a = perturb_and_dscrop(img, ds_transforms, augmentation_params, target_sizes)
    return img_a

def load_and_process_image_fixed_test_col(img_index, ds_transforms, augmentation_transforms, target_sizes=None):
    img_id = test_data[img_index]
    img = load_data.load_fits_test_col(img_id)
    return [img]

class LoadAndProcessNeg(object):                                                       ##USATA

    def __init__(self, ds_transforms, augmentation_params, target_sizes=None):
        self.ds_transforms = ds_transforms
        self.augmentation_params = augmentation_params
        self.target_sizes = target_sizes

    def __call__(self, img_index):
        return load_and_process_image_neg(img_index, self.ds_transforms, self.augmentation_params, self.target_sizes)

        
class LoadAndProcessLens(object):                                                       ##USATA

    def __init__(self, ds_transforms, augmentation_params, target_sizes=None):
        self.ds_transforms = ds_transforms
        self.augmentation_params = augmentation_params
        self.target_sizes = target_sizes

    def __call__(self, img_index):
        return load_and_process_image_lens(img_index, self.ds_transforms, self.augmentation_params, self.target_sizes)

class LoadAndProcessSource(object):                                                       ##USATA

    def __init__(self, ds_transforms, augmentation_params, target_sizes=None):
        self.ds_transforms = ds_transforms
        self.augmentation_params = augmentation_params
        self.target_sizes = target_sizes

    def __call__(self, img_index):
        return load_and_process_image_source(img_index, self.ds_transforms, self.augmentation_params, self.target_sizes)
    
class LoadAndProcessFixedTest(object):
    def __init__(self, ds_transforms, augmentation_transforms, target_sizes=None):
        self.ds_transforms = ds_transforms
        self.augmentation_transforms = augmentation_transforms
        self.target_sizes = target_sizes

    def __call__(self, img_index):
        return load_and_process_image_fixed_test(img_index, self.ds_transforms, self.augmentation_transforms, self.target_sizes)

class LoadAndProcessNegCol(object):  
    def __init__(self, ds_transforms, augmentation_params, target_sizes=None):
        self.ds_transforms = ds_transforms
        self.augmentation_params = augmentation_params
        self.target_sizes = target_sizes

    def __call__(self, img_index):
        return load_and_process_image_neg_col(img_index, self.ds_transforms, self.augmentation_params, self.target_sizes)

class LoadAndProcessPosCol(object):
    def __init__(self, ds_transforms, augmentation_params, target_sizes=None):
        self.ds_transforms = ds_transforms
        self.augmentation_params = augmentation_params
        self.target_sizes = target_sizes

    def __call__(self, img_index):
        return load_and_process_image_pos_col(img_index, self.ds_transforms, self.augmentation_params, self.target_sizes)


          
class LoadAndProcessFixedTestCol(object):
    def __init__(self, ds_transforms, augmentation_transforms, target_sizes=None):
        self.ds_transforms = ds_transforms
        self.augmentation_transforms = augmentation_transforms
        self.target_sizes = target_sizes

    def __call__(self, img_index):
        return load_and_process_image_fixed_test_col(img_index, self.ds_transforms, self.augmentation_transforms, self.target_sizes)

        
      
def realtime_augmented_data_gen_neg(num_chunks=None,chunk_size=CHUNK_SIZE, augmentation_params=default_augmentation_params,          #keep
                                ds_transforms=ds_transforms_default, target_sizes=None, processor_class=LoadAndProcessNeg, normalize=True, resize= False, resize_shape=(60,60)):
    """
    new version, using Pool.imap instead of Pool.map, to avoid the data structure conversion
    from lists to numpy arrays afterwards.
    """

    if target_sizes is None: 
        target_sizes = [(53, 53) for _ in range(len(ds_transforms))]
    n = 0 
    while True:
        if num_chunks is not None and n >= num_chunks:
            break
        selected_indices = select_indices(num_neg, chunk_size)
        labels = np.zeros(chunk_size)
        process_func = processor_class(ds_transforms, augmentation_params, target_sizes)    
        
        target_arrays = [np.empty((chunk_size, size_x, size_y, IMAGE_NUM_CHANNELS), dtype='float32') for size_x, size_y in target_sizes]
        pool = mp.Pool(NUM_PROCESSES)
        gen = pool.imap(process_func, selected_indices, chunksize=loadsize) # lower chunksize seems to help to keep memory usage in check
        
        for k, imgs in enumerate(gen):
            for i, image in enumerate(imgs):
              scale_min = 0
              scale_max = image.max()
              image.clip(min=scale_min, max=scale_max)
              indices = np.where(image < 0)
              image[indices] = 0.0
              new_img = np.sqrt(image)
              if normalize:
                new_img = (new_img / new_img.max()*255.) 
              if resize:
                new_img=Image.fromarray(new_img)
                new_img=new_img.resize(resize_shape, resample=Image.LANCZOS)
              target_arrays[i][k] = new_img
        pool.close()
        pool.join()
        
        target_arrays.append(labels.astype(np.int32))
        
        yield target_arrays, chunk_size
        n += 1
        
        
def realtime_augmented_data_gen_pos(num_chunks=None,chunk_size=CHUNK_SIZE, augmentation_params=default_augmentation_params,          #keep
                                ds_transforms=ds_transforms_default, target_sizes=None, processor_class=LoadAndProcessSource, processor_class2=LoadAndProcessLens, normalize=True, resize=False, resize_shape=(60,60), range_min=0.02, range_max=0.5):
    """
    new version, using Pool.imap instead of Pool.map, to avoid the data structure conversion
    from lists to numpy arrays afterwards.
    """
    if target_sizes is None:
        target_sizes = [(53, 53) for _ in range(len(ds_transforms))]
    n = 0 
    while True:
        if num_chunks is not None and n >= num_chunks:
            break        
        selected_indices_sources = select_indices(num_sources, chunk_size)    
        selected_indices_lenses = select_indices(num_lenses, chunk_size)
        
        labels = np.ones(chunk_size)
        
        process_func = processor_class(ds_transforms, augmentation_params, target_sizes)    #SOURCE
        process_func2 = processor_class2(ds_transforms, augmentation_params, target_sizes)     #LENS
        
        target_arrays_pos = [np.empty((chunk_size, size_x, size_y, IMAGE_NUM_CHANNELS), dtype='float32') for size_x, size_y in target_sizes]
        
        pool1 = mp.Pool(NUM_PROCESSES)
        gen = pool1.imap(process_func, selected_indices_sources, chunksize=loadsize) 
        
        pool2 = mp.Pool(NUM_PROCESSES)
        gen2 = pool2.imap(process_func2, selected_indices_lenses, chunksize=loadsize) 
        
        k=0
        for source,lens in zip(gen,gen2):
          source=np.array(source)
          lens=np.array(lens)
          imageData=lens+source/np.amax(source)*np.amax(lens)*np.random.uniform(range_min,range_max)
          scale_min = 0
          scale_max = imageData.max()
          imageData.clip(min=scale_min, max=scale_max)
          indices = np.where(imageData < 0)
          imageData[indices] = 0.0
          new_img = np.sqrt(imageData)
          if normalize:
            new_img =  (new_img / new_img.max()*255.) 
          if resize:
              new_img=Image.fromarray(new_img)
              new_img=new_img.resize(resize_shape, resample=Image.LANCZOS)
          target_arrays_pos[0][k] = new_img
          k+=1
        
        pool1.close()
        pool1.join()
        pool2.close()
        pool2.join()
        target_arrays_pos.append(labels.astype(np.int32))
        
        yield target_arrays_pos, chunk_size
        n += 1


        
def realtime_augmented_data_gen_neg_col(num_chunks=None,chunk_size=CHUNK_SIZE, augmentation_params=default_augmentation_params,          #keep
                                ds_transforms=ds_transforms_default, target_sizes=None, processor_class=LoadAndProcessNegCol):
    """
    new version, using Pool.imap instead of Pool.map, to avoid the data structure conversion
    from lists to numpy arrays afterwards.
    """

    if target_sizes is None: 
        target_sizes = [(53, 53) for _ in range(len(ds_transforms))]
    n = 0 
    while True:
        if num_chunks is not None and n >= num_chunks:
            
            break
        selected_indices = select_indices(num_neg, chunk_size)
        labels = np.zeros(chunk_size)
        process_func = processor_class(ds_transforms, augmentation_params, target_sizes)    
        
        target_arrays = [np.empty((chunk_size, size_x, size_y, IMAGE_NUM_CHANNELS), dtype='float32') for size_x, size_y in target_sizes]
        pool = mp.Pool(NUM_PROCESSES)
        gen = pool.imap(process_func, selected_indices, chunksize=loadsize) # lower chunksize seems to help to keep memory usage in check
        
        for k, imgs in enumerate(gen):
            for i, image in enumerate(imgs):
              target_arrays[i][k] =	image 
        pool.close()
        pool.join()
        
        target_arrays.append(labels.astype(np.int32))
        
        yield target_arrays, chunk_size
        n += 1

def realtime_augmented_data_gen_pos_col(num_chunks=None,chunk_size=CHUNK_SIZE, augmentation_params=default_augmentation_params,          #keep
                                ds_transforms=ds_transforms_default, target_sizes=None, processor_class=LoadAndProcessPosCol):
    """
    new version, using Pool.imap instead of Pool.map, to avoid the data structure conversion
    from lists to numpy arrays afterwards.
    """
    if target_sizes is None:
        target_sizes = [(53, 53) for _ in range(len(ds_transforms))]
    n = 0 
    while True:
        if num_chunks is not None and n >= num_chunks:
            
            break
        selected_indices1 = select_indices(num_lenses, chunk_size)
        selected_indices2 = select_indices(num_sources, chunk_size)
        
        selected_indices=zip(selected_indices1,selected_indices2)
        
        labels = np.ones(chunk_size)
        
        process_func = processor_class(ds_transforms, augmentation_params, target_sizes)    
        
        target_arrays = [np.empty((chunk_size, size_x, size_y, IMAGE_NUM_CHANNELS), dtype='float32') for size_x, size_y in target_sizes]
        pool = mp.Pool(NUM_PROCESSES)
        gen = pool.imap(process_func, selected_indices, chunksize=loadsize) # lower chunksize seems to help to keep memory usage in check
        
        for k, imgs in enumerate(gen):
            for i, image in enumerate(imgs):
              target_arrays[i][k] =	image
              
        pool.close()
        pool.join()
        
        target_arrays.append(labels.astype(np.int32))
        
        yield target_arrays, chunk_size
        n += 1


def realtime_fixed_augmented_data_test_col(ds_transforms=ds_transforms_default, augmentation_transforms=[tform_identity],     #keep
                                        chunk_size=4000, target_sizes=None, processor_class=LoadAndProcessFixedTestCol):
    """
    by default, only the identity transform is in the augmentation list, so no augmentation occurs (only ds_transforms are applied).
    """
    selected_indices=np.arange(num_test)
    num_ids_per_chunk = (chunk_size // len(augmentation_transforms)) # number of datapoints per chunk - each datapoint is multiple entries!
    num_chunks = int(np.ceil(len(selected_indices) / float(num_ids_per_chunk)))

    if target_sizes is None:
        target_sizes = [(53, 53) for _ in range(len(ds_transforms))]

    process_func = processor_class(ds_transforms, augmentation_transforms, target_sizes)

    for n in range(num_chunks):
        indices_n = selected_indices[n * num_ids_per_chunk:(n+1) * num_ids_per_chunk]
        current_chunk_size = len(indices_n) * len(augmentation_transforms) # last chunk will be shorter!

        target_arrays = [np.empty((current_chunk_size, size_x, size_y, IMAGE_NUM_CHANNELS), dtype='float32') for size_x, size_y in target_sizes]

        pool = mp.Pool(NUM_PROCESSES)
        gen = pool.imap(process_func, indices_n, chunksize=loadsize) # lower chunksize seems to help to keep memory usage in check

        for k, imgs_aug in enumerate(gen):
            for i, imgs in enumerate(imgs_aug):
                    target_arrays[i][k] = imgs

        pool.close()
        pool.join()

        yield target_arrays, current_chunk_size

def realtime_fixed_augmented_data_test(ds_transforms=ds_transforms_default, augmentation_transforms=[tform_identity],    #keep
                                        chunk_size=500,target_sizes=None, processor_class=LoadAndProcessFixedTest):
    """
    by default, only the identity transform is in the augmentation list, so no augmentation occurs (only ds_transforms are applied).
    """
    selected_indices=np.arange(num_test)
    num_ids_per_chunk = (chunk_size // len(augmentation_transforms)) # number of datapoints per chunk - each datapoint is multiple entries!
    num_chunks = int(np.ceil(len(selected_indices) / float(num_ids_per_chunk)))

    if target_sizes is None: 
        target_sizes = [(53, 53) for _ in range(len(ds_transforms))]

    process_func = processor_class(ds_transforms, augmentation_transforms, target_sizes)

    for n in range(num_chunks):
        indices_n = selected_indices[n * num_ids_per_chunk:(n+1) * num_ids_per_chunk]
        current_chunk_size = len(indices_n) * len(augmentation_transforms) # last chunk will be shorter!

        target_arrays = [np.empty((current_chunk_size, size_x, size_y, IMAGE_NUM_CHANNELS), dtype='float32') for size_x, size_y in target_sizes]

        pool = mp.Pool(NUM_PROCESSES)
        gen = pool.imap(process_func, indices_n, chunksize=100) # lower chunksize seems to help to keep memory usage in check

        for k, imgs_aug in enumerate(gen):
            for i, imgs in enumerate(imgs_aug):
                    target_arrays[i][k] = imgs
 
        pool.close()
        pool.join()

        yield target_arrays, current_chunk_size
        
