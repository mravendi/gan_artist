# Copyright (c) 2017, NVIDIA CORPORATION. All rights reserved.
#
# This work is licensed under the Creative Commons Attribution-NonCommercial
# 4.0 International License. To view a copy of this license, visit
# http://creativecommons.org/licenses/by-nc/4.0/ or send a letter to
# Creative Commons, PO Box 1866, Mountain View, CA 94042, USA.

import os
import sys
import io
import glob
import pickle
import argparse
import threading
import queue
#import Queue
#import queue
import traceback
import numpy as np
import scipy.ndimage
import PIL.Image
from PIL import Image
import h5py # conda install h5py

#----------------------------------------------------------------------------

class HDF5Exporter:
    def __init__(self, h5_filename, resolution, channels=3):
        rlog2 = int(np.floor(np.log2(resolution)))
        assert resolution == 2 ** rlog2
        self.resolution = resolution
        self.channels = channels
        self.h5_file = h5py.File(h5_filename, 'w')
        self.h5_lods = []
        self.buffers = []
        self.buffer_sizes = []
        for lod in range(rlog2, -1, -1):
            r = 2 ** lod; c = channels
            bytes_per_item = c * (r ** 2)
            chunk_size = int(np.ceil(128.0 / bytes_per_item))
            buffer_size = int(np.ceil(512.0 * np.exp2(20) / bytes_per_item))
            #change to channel last
            lod = self.h5_file.create_dataset('data%dx%d' % (r,r), shape=(0,r,r,c), dtype=np.uint8,
                maxshape=(None,r,r,c), chunks=(chunk_size,r,r,c), compression='gzip', compression_opts=4)
            
            self.h5_lods.append(lod)
            self.buffers.append(np.zeros((buffer_size,r,r,c), dtype=np.uint8))
            self.buffer_sizes.append(0)

    def close(self):
        for lod in range(len(self.h5_lods)):
            self.flush_lod(lod)
        self.h5_file.close()

    def add_images(self, img):
        assert img.ndim == 4 and img.shape[1] == self.channels and img.shape[2] == img.shape[3]
        assert img.shape[2] >= self.resolution and img.shape[2] == 2 ** int(np.floor(np.log2(img.shape[2])))
        for lod in range(len(self.h5_lods)):
            while img.shape[2] > self.resolution / (2 ** lod):
                img = img.astype(np.float32)
                img = (img[:, :, 0::2, 0::2] + img[:, :, 0::2, 1::2] + img[:, :, 1::2, 0::2] + img[:, :, 1::2, 1::2]) * 0.25
            quant = np.uint8(np.clip(np.round(img), 0, 255))
            ofs = 0
            while ofs < quant.shape[0]:
                num = min(quant.shape[0] - ofs, self.buffers[lod].shape[0] - self.buffer_sizes[lod])
                self.buffers[lod][self.buffer_sizes[lod] : self.buffer_sizes[lod] + num] = quant[ofs : ofs + num]
                self.buffer_sizes[lod] += num
                if self.buffer_sizes[lod] == self.buffers[lod].shape[0]:
                    self.flush_lod(lod)
                ofs += num

    def add_images_channel_last(self, img):
        #print(img.shape)
        assert img.ndim == 4 and img.shape[3] == self.channels and img.shape[1] == img.shape[2]
        assert img.shape[2] >= self.resolution and img.shape[2] == 2 ** int(np.floor(np.log2(img.shape[2])))
        for lod in range(len(self.h5_lods)):
            while img.shape[2] > self.resolution / (2 ** lod):
                img = img.astype(np.float32)
                img =   (img[:,  0::2, 0::2, :] + 
                        img[:,  0::2, 1::2,  :] + 
                        img[:,  1::2, 0::2,  :] + 
                        img[:,  1::2, 1::2,  :]) * 0.25

            quant = np.uint8(np.clip(np.round(img), 0, 255))
            ofs = 0
            while ofs < quant.shape[0]:
                num = min(quant.shape[0] - ofs, self.buffers[lod].shape[0] - self.buffer_sizes[lod])
                
                #print("self.buffers.shape:",self.buffers[0].shape)

                self.buffers[lod][ self.buffer_sizes[lod] : self.buffer_sizes[lod] + num] = quant[ofs : ofs + num]
                self.buffer_sizes[lod] += num
                if self.buffer_sizes[lod] == self.buffers[lod].shape[0]:
                    self.flush_lod(lod)
                ofs += num

    def num_images(self):
        return self.h5_lods[0].shape[0] + self.buffer_sizes[0]
        
    def flush_lod(self, lod):
        num = self.buffer_sizes[lod]
        if num > 0:
            self.h5_lods[lod].resize(self.h5_lods[lod].shape[0] + num, axis=0)
            self.h5_lods[lod][-num:] = self.buffers[lod][:num]
            self.buffer_sizes[lod] = 0

#----------------------------------------------------------------------------

class ExceptionInfo(object):
    def __init__(self):
        self.type, self.value = sys.exc_info()[:2]
        self.traceback = traceback.format_exc()

#----------------------------------------------------------------------------

class WorkerThread(threading.Thread):
    def __init__(self, task_queue):
        threading.Thread.__init__(self)
        self.task_queue = task_queue

    def run(self):
        while True:
            func, args, result_queue = self.task_queue.get()
            if func is None:
                break
            try:
                result = func(*args)
            except:
                result = ExceptionInfo()
            result_queue.put((result, args))

#----------------------------------------------------------------------------

class ThreadPool(object):
    def __init__(self, num_threads):
        assert num_threads >= 1
        self.task_queue = queue.Queue()
        self.result_queues = dict()
        self.num_threads = num_threads
        for idx in range(self.num_threads):
            thread = WorkerThread(self.task_queue)
            thread.daemon = True
            thread.start()

    def add_task(self, func, args=()):
        assert hasattr(func, '__call__') # must be a function
        if func not in self.result_queues:
            self.result_queues[func] = queue.Queue()
        self.task_queue.put((func, args, self.result_queues[func]))

    def get_result(self, func, verbose_exceptions=True): # returns (result, args)
        result, args = self.result_queues[func].get()
        if isinstance(result, ExceptionInfo):
            if verbose_exceptions:
                #print('\n\nWorker thread caught an exception:\n' + result.traceback + '\n', end=' ')
                print('\n\nWorker thread caught an exception:\n' + result.traceback + '\n')
            raise result.type(result.value)
        return result, args

    def finish(self):
        for idx in range(self.num_threads):
            self.task_queue.put((None, (), None))

    def __enter__(self): # for 'with' statement
        return self

    def __exit__(self, *excinfo):
        self.finish()

    def process_items_concurrently(self, item_iterator, process_func=lambda x: x, pre_func=lambda x: x, post_func=lambda x: x, max_items_in_flight=None):
        if max_items_in_flight is None: max_items_in_flight = self.num_threads * 4
        assert max_items_in_flight >= 1
        results = []
        retire_idx = [0]

        def task_func(prepared, idx):
            return process_func(prepared)
           
        def retire_result():
            processed, (prepared, idx) = self.get_result(task_func)
            results[idx] = processed
            while retire_idx[0] < len(results) and results[retire_idx[0]] is not None:
                yield post_func(results[retire_idx[0]])
                results[retire_idx[0]] = None
                retire_idx[0] += 1
    
        for idx, item in enumerate(item_iterator):
            prepared = pre_func(item)
            results.append(None)
            self.add_task(func=task_func, args=(prepared, idx))
            while retire_idx[0] < idx - max_items_in_flight + 2:
                for res in retire_result(): yield res
        while retire_idx[0] < len(results):
            for res in retire_result(): yield res

#----------------------------------------------------------------------------

def create_celeba_channel_last(h5_filename, celeba_dir, cx=89, cy=121):
    print('Creating CelebA channel last dataset %s from %s' % (h5_filename, celeba_dir))
    #glob_pattern = os.path.join(celeba_dir, 'img_align_celeba_png', '*.png')
    glob_pattern = os.path.join(celeba_dir, '*.jpg')
    image_filenames = sorted(glob.glob(glob_pattern))
    num_images = 5000 #202599
    #num_images = len(image_filenames)
    print((len(image_filenames)))
    test = []
    for i in image_filenames:
        a=i.split('/')[-1]
        a=a.split('.')[0]
        test.append(int(a))
    for i in range(1,len(test)):
        if(test[i]!=test[i-1]+1):
            print((test[i-1],test[i]))

    #if len(image_filenames) != num_images:
    #    print('Error: Expected to find %d images in %s' % (num_images, glob_pattern))
    #    return
    
    h5 = HDF5Exporter(h5_filename, 128, 3)
    for idx in range(num_images):
        print('%d / %d\r' % (idx, num_images))
        img = PIL.Image.open(image_filenames[idx])
        img=img.resize((128,128))
        if img.mode != "RGB":
            img=img.convert('RGB')
        img = np.asarray(img)
        
        #img = np.asarray(PIL.Image.open(image_filenames[idx]))
        #assert img.shape == (218, 178, 3)
        #img = img[cy - 64 : cy + 64, cx - 64 : cx + 64]
        #img = img.transpose(2, 0, 1) # HWC => CHW
        h5.add_images_channel_last(img[np.newaxis])

    print('%-40s\r' % 'Flushing data...')
    h5.close()
    print('%-40s\r' % '')
    print('Added %d images.' % num_images)


def create_data_channel_last(h5_filename, path2images, imgHW=(128,128)):
    print('Creating data channel last dataset %s from %s' % (h5_filename, path2images))
    #glob_pattern = os.path.join(celeba_dir, 'img_align_celeba_png', '*.png')
    glob_pattern = os.path.join(path2images, '*.jpg')
    image_filenames = sorted(glob.glob(glob_pattern))
    num_images = len(image_filenames)
    num_images=10000
    print((len(image_filenames)))
    
    test = []
    for i in image_filenames:
        a=i.split('/')[-1]
        a=a.split('.')[0]
        test.append(int(a))
    for i in range(1,len(test)):
        if(test[i]!=test[i-1]+1):
            print((test[i-1],test[i]))

    h,w=imgHW
    h5 = HDF5Exporter(h5_filename, resolution=h, channels=3)
    for idx in range(num_images):
        print('%d / %d\r' % (idx, num_images))
        img = PIL.Image.open(image_filenames[idx])
        try:
            img=img.resize((w,h),PIL.Image.BICUBIC)
            if img.mode != "RGB":
                img=img.convert('RGB')
            img = np.asarray(img)
            
            h5.add_images_channel_last(img[np.newaxis])
        except:
            print("skip this image!")            
    print('%-40s\r' % 'Flushing data...')
    h5.close()
    print('%-40s\r' % '')
    print('Added %d images.' % num_images)


def imgResizeWithPad(im_path,desired_size=512):
    im = Image.open(im_path)
    old_size = im.size  # old_size[0] is in (width, height) format
    ratio = float(desired_size)/max(old_size)
    new_size = tuple([int(x*ratio) for x in old_size])
    im = im.resize(new_size, Image.ANTIALIAS)

    # create a new image and paste the resized on it
    new_im = Image.new("RGB", (desired_size, desired_size))
    new_im.paste(im, ((desired_size-new_size[0])//2,
                    (desired_size-new_size[1])//2))
    return new_im


def create_data_channel_last2(h5_filename, path2images, imgHW=(128,128)):
    print('Creating data channel last dataset %s from %s' % (h5_filename, path2images))
    #glob_pattern = os.path.join(celeba_dir, 'img_align_celeba_png', '*.png')
    glob_pattern = os.path.join(path2images, '*.jpg')
    image_filenames = sorted(glob.glob(glob_pattern))
    num_images = len(image_filenames)
    num_images=15000
    print((len(image_filenames)))
    
    test = []
    for i in image_filenames:
        a=i.split('/')[-1]
        a=a.split('.')[0]
        test.append(int(a))
    for i in range(1,len(test)):
        if(test[i]!=test[i-1]+1):
            print((test[i-1],test[i]))

    h,w=imgHW
    h5 = HDF5Exporter(h5_filename, resolution=h, channels=3)
    for idx in range(num_images):
        print('%d / %d\r' % (idx, num_images))
        try:
            img=imgResizeWithPad(image_filenames[idx],w)
            if img.mode != "RGB":
                img=img.convert('RGB')
            img_array = np.asarray(img)
            h5.add_images_channel_last(img_array[np.newaxis])
        except:
            print("skip this image!")            
    print('%-40s\r' % 'Flushing data...')
    h5.close()
    print('%-40s\r' % '')
    print('Added %d images.' % num_images)


#----------------------------------------------------------------------------

def execute_cmdline(argv):
    prog = argv[0]
    parser = argparse.ArgumentParser(
        prog        = prog,
        description = 'Tool for creating, extracting, and visualizing HDF5 datasets.',
        epilog      = 'Type "%s <command> -h" for more information.' % prog)
        
    subparsers = parser.add_subparsers(dest='command')
    def add_command(cmd, desc, example=None):
        epilog = 'Example: %s %s' % (prog, example) if example is not None else None
        return subparsers.add_parser(cmd, description=desc, help=desc, epilog=epilog)

    p.add_argument(     'h5_filename',      help='HDF5 file to inspect')

    p = add_command(    'create_celeba_channel_last',    'Create HDF5 channel last dataset for CelebA.',
                                            'create_celeba celeba-128x128.h5 ~/celeba')

    p.add_argument(     'h5_filename',      help='HDF5 file to create')
    p.add_argument(     'celeba_dir',       help='Directory to read CelebA data from')
    p.add_argument(     '--cx',             help='Center X coordinate (default: 89)', type=int, default=89)
    p.add_argument(     '--cy',             help='Center Y coordinate (default: 121)', type=int, default=121)

    args = parser.parse_args(argv[1:])
    func = globals()[args.command]
    del args.command
    func(**vars(args))

#----------------------------------------------------------------------------

if __name__ == "__main__":
    execute_cmdline(sys.argv)


#create_celeba_channel_last('datasets/celeba_128x128.h5', 'datasets/img_align_celeba', cx=89, cy=121)


#----------------------------------------------------------------------------
