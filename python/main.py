﻿from __future__ import print_function
import numpy as np
# import sys
import os
backend="tensorflow"
os.environ['KERAS_BACKEND'] = backend
import argparse
from datadownload import download_celeb_a
#from h5tool import create_data_channel_last
from h5tool import create_data_channel_last2 as  create_data_channel_last
import config

###################################################################
# Variables                                                       #
# When launching project or scripts from Visual Studio,           #
# input_dir and output_dir are passed as arguments.               #
# Users could set them from the project setting page.             #
###################################################################

input_dir = None
output_dir = None
log_dir = None


#################################################################################
# Keras configs.                                                                #
# Please refer to https://keras.io/backend .                                    #
#################################################################################

# import keras
from keras import backend as K

#K.set_floatx('float32')
#String: 'float16', 'float32', or 'float64'.

#K.set_epsilon(1e-05)
#float. Sets the value of the fuzz factor used in numeric expressions.

K.set_image_data_format('channels_last')
#data_format: string. 'channels_first' or 'channels_last'.


#################################################################################
# Keras imports.                                                                #
#################################################################################

from keras.models import Model
from keras.models import Sequential
from keras.layers import Input
from keras.layers import Lambda
from keras.layers import Layer
from keras.layers import Dense
from keras.layers import Dropout
from keras.layers import Activation
from keras.layers import Flatten
from keras.layers import Conv2D
from keras.layers import MaxPooling2D
from keras.optimizers import SGD
from keras.optimizers import RMSprop
from train import *

def main():

    np.random.seed(config.random_seed)
    func_params = config.train

    func_name = func_params['func']
    del func_params['func']
    globals()[func_name](**func_params)
    exit(0)

def renameFileNames(data_dir):
    #data_dir="./datasets/landscape/"
    glob_pattern = os.path.join(data_dir, '*.jpg')
    image_filenames = sorted(glob.glob(glob_pattern))
    sampleName=image_filenames[0]
    sampleName=os.path.basename(sampleName).split(".")[0]
    if sampleName.isdigit():
        return
    num_images = len(image_filenames)
    print("there are %s images " %(num_images))
    for i,imgfn in enumerate(image_filenames):
        dirname=os.path.dirname(imgfn)
        ii=str(i+1).rjust(5,"0")
        imgfn_new=os.path.join(dirname,ii+".jpg")
        os.rename(imgfn, imgfn_new)
    print("rename completed!")
    print("-"*50)
    print("-"*50)
    return

def download(genre,H,W,data_dir):
    h5_name=genre+"_"+str(H)+"by"+str(W)+".h5"
    h5path = os.path.join(os.getcwd(),'datasets',h5_name);
    if os.path.exists(h5path):
        print(h5path+ "found!")
        return

    data_dir=os.path.join(data_dir,genre)
    renameFileNames(data_dir)    
    glob_pattern = os.path.join(data_dir, '*.jpg')
    image_filenames = sorted(glob.glob(glob_pattern))
    num_images = len(image_filenames)
    print("there are %s images " %(num_images))
    # create_celeba_channel_last(h5path, data_dir, cx=89, cy=121)
    create_data_channel_last(h5path, data_dir, imgHW=(H,W))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_dir", type=str, 
                        default='datasets', 
                        help="Input directory where where training dataset and meta data are saved", 
                        required=False
                        )
    parser.add_argument("--result_dir", type=str, 
                        default='results', 
                        help="Input directory where where logs and models are saved", 
                        required=False
                        )
    parser.add_argument("--resume_dir",type = str,
                        default = None,
                        help="whether resume model and where the model are saved",
                        required = False)
    #parser.add_argument("--resume_kimg",type = float,
                        #default = 0.0,
                        #help="previous trained images in thousands",
                        #required = False)
    #args, unknown = parser.parse_known_args()
    #config.data_dir = os.path.join(os.getcwd(),args.data_dir)
    #config.result_dir = os.path.join(os.getcwd(),args.result_dir)
    #if hasattr(args,'resume_dir') and args.resume_dir != None:
        #config.train.update(resume_network=args.resume_dir)
    #if hasattr(args,'resume_kimg') and args.resume_kimg != None:
        #config.train.update(resume_kimg=args.resume_kimg)
    
    download(config.genre,config.H,config.W,config.data_dir)
    main()
