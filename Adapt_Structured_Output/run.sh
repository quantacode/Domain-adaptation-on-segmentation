#!/usr/bin/env bash

CUDA_VISIBLE_DEVICES=0 python train_synthia2cityscapes_multi.py \
--ignore-label 250 \
--snapshot-dir ./snapshots/GTA2Cityscapes_multi \
--lambda-seg 0.0