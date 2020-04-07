import argparse
import torch
import torch.nn as nn
from torch.utils import data, model_zoo
import numpy as np
import pickle
from torch.autograd import Variable
import torch.optim as optim
import scipy.misc
import torch.backends.cudnn as cudnn
import torch.nn.functional as F
import sys
import os
import os.path as osp
import matplotlib.pyplot as plt
import random
import ipdb
from tensorboardX import SummaryWriter
from PIL import Image

from model.deeplab_multi import Res_Deeplab
from model.discriminator import FCDiscriminator
from utils.loss import CrossEntropy2d
from dataset.Synthia_dataset import SynthiaDataSet
# from dataset.cityscapes_dataset import cscape_val
from dataset.cityscapes_evaluate_dataset import cityscapesDataSet
from tools.sync_batchnorm.replicate import patch_replication_callback
from compute_iou import compute_mIoU

IMG_MEAN = np.array((104.00698793, 116.66876762, 122.67891434), dtype=np.float32)

MODEL = 'DeepLab'
BATCH_SIZE = 1
ITER_SIZE = 1
NUM_WORKERS = 0
DATA_DIRECTORY = '/data/datasets/da/synthia/RAND_CITYSCAPES/'
DATA_LIST_PATH = './dataset/Synthia_list/train.txt'
IGNORE_LABEL = 255
INPUT_SIZE = '1280,720'
DATA_DIRECTORY_TARGET = '/data/datasets/da/cityscapes/leftImg8bit/'
DATA_LIST_PATH_TARGET = './dataset/cityscapes_list/train.txt'
INPUT_SIZE_TARGET = '1024,512'
LEARNING_RATE = 2.5e-4
MOMENTUM = 0.9
NUM_CLASSES = 19
NUM_STEPS = 250000000
NUM_STEPS_STOP = 80000  # early stopping
POWER = 0.9
RANDOM_SEED = 1234
RESTORE_FROM = 'http://vllab.ucmerced.edu/ytsai/CVPR18/DeepLab_resnet_pretrained_init-f81d91e8.pth'
SAVE_NUM_IMAGES = 2
SAVE_PRED_EVERY = 5000
SAVE_PATH = './result/cityscapes'
SNAPSHOT_DIR = './snapshots/'
WEIGHT_DECAY = 0.0005

LEARNING_RATE_D = 1e-4
LAMBDA_SEG = 0.1
LAMBDA_ADV_TARGET1 = 0.0002
LAMBDA_ADV_TARGET2 = 0.001

TARGET = 'cityscapes'
SET = 'train'


def get_arguments():
    """Parse all the arguments provided from the CLI.

    Returns:
      A list of parsed arguments.
    """
    parser = argparse.ArgumentParser(description="DeepLab-ResNet Network")
    parser.add_argument("--model", type=str, default=MODEL,
                        help="available options : DeepLab")
    parser.add_argument("--target", type=str, default=TARGET,
                        help="available options : cityscapes")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE,
                        help="Number of images sent to the network in one step.")
    parser.add_argument("--iter-size", type=int, default=ITER_SIZE,
                        help="Accumulate gradients for ITER_SIZE iterations.")
    parser.add_argument("--num-workers", type=int, default=NUM_WORKERS,
                        help="number of workers for multithread dataloading.")
    parser.add_argument("--data-dir", type=str, default=DATA_DIRECTORY,
                        help="Path to the directory containing the source dataset.")
    parser.add_argument("--data-list", type=str, default=DATA_LIST_PATH,
                        help="Path to the file listing the images in the source dataset.")
    parser.add_argument("--ignore-label", type=int, default=IGNORE_LABEL,
                        help="The index of the label to ignore during the training.")
    parser.add_argument("--input-size", type=str, default=INPUT_SIZE,
                        help="Comma-separated string with height and width of source images.")
    parser.add_argument("--data-dir-target", type=str, default=DATA_DIRECTORY_TARGET,
                        help="Path to the directory containing the target dataset.")
    parser.add_argument("--data-list-target", type=str, default=DATA_LIST_PATH_TARGET,
                        help="Path to the file listing the images in the target dataset.")
    parser.add_argument("--input-size-target", type=str, default=INPUT_SIZE_TARGET,
                        help="Comma-separated string with height and width of target images.")
    parser.add_argument("--is-training", action="store_true",
                        help="Whether to updates the running means and variances during the training.")
    parser.add_argument("--learning-rate", type=float, default=LEARNING_RATE,
                        help="Base learning rate for training with polynomial decay.")
    parser.add_argument("--learning-rate-D", type=float, default=LEARNING_RATE_D,
                        help="Base learning rate for discriminator.")
    parser.add_argument("--lambda-seg", type=float, default=LAMBDA_SEG,
                        help="lambda_seg.")
    parser.add_argument("--lambda-adv-target1", type=float, default=LAMBDA_ADV_TARGET1,
                        help="lambda_adv for adversarial training.")
    parser.add_argument("--lambda-adv-target2", type=float, default=LAMBDA_ADV_TARGET2,
                        help="lambda_adv for adversarial training.")
    parser.add_argument("--momentum", type=float, default=MOMENTUM,
                        help="Momentum component of the optimiser.")
    parser.add_argument("--not-restore-last", action="store_true",
                        help="Whether to not restore last (FC) layers.")
    parser.add_argument("--num-classes", type=int, default=NUM_CLASSES,
                        help="Number of classes to predict (including background).")
    parser.add_argument("--num-steps", type=int, default=NUM_STEPS,
                        help="Number of training steps.")
    parser.add_argument("--num-steps-stop", type=int, default=NUM_STEPS_STOP,
                        help="Number of training steps for early stopping.")
    parser.add_argument("--power", type=float, default=POWER,
                        help="Decay parameter to compute the learning rate.")
    parser.add_argument("--random-mirror", action="store_true",
                        help="Whether to randomly mirror the inputs during the training.")
    parser.add_argument("--random-scale", action="store_true",
                        help="Whether to randomly scale the inputs during the training.")
    parser.add_argument("--random-seed", type=int, default=RANDOM_SEED,
                        help="Random seed to have reproducible results.")
    parser.add_argument("--restore-from", type=str, default=RESTORE_FROM,
                        help="Where restore model parameters from.")
    parser.add_argument("--save-num-images", type=int, default=SAVE_NUM_IMAGES,
                        help="How many images to save.")
    parser.add_argument("--save-pred-every", type=int, default=SAVE_PRED_EVERY,
                        help="Save summaries and checkpoint every often.")
    parser.add_argument("--save", type=str, default=SAVE_PATH,
                        help="Where to save snapshots of the model.")
    parser.add_argument("--snapshot-dir", type=str, default=SNAPSHOT_DIR,
                        help="Where to save snapshots of the model.")
    parser.add_argument("--weight-decay", type=float, default=WEIGHT_DECAY,
                        help="Regularisation parameter for L2-loss.")
    parser.add_argument("--gpu", type=int, default=0,
                        help="choose gpu device.")
    parser.add_argument("--set", type=str, default=SET,
                        help="choose adaptation set.")
    return parser.parse_args()


args = get_arguments()

palette = [128, 64, 128, 244, 35, 232, 70, 70, 70, 102, 102, 156, 190, 153, 153, 153, 153, 153, 250, 170, 30,
           220, 220, 0, 107, 142, 35, 152, 251, 152, 70, 130, 180, 220, 20, 60, 255, 0, 0, 0, 0, 142, 0, 0, 70,
           0, 60, 100, 0, 80, 100, 0, 0, 230, 119, 11, 32]
zero_pad = 256 * 3 - len(palette)
for i in range(zero_pad):
    palette.append(0)


def colorize_mask(mask):
    # mask: numpy array of the mask
    new_mask = Image.fromarray(mask.astype(np.uint8)).convert('P')
    new_mask.putpalette(palette)

    return new_mask

def loss_calc(pred, label, gpu):
    """
    This function returns cross entropy loss for semantic segmentation
    """
    # out shape batch_size x channels x h x w -> batch_size x channels x h x w
    # label shape h x w x 1 x batch_size  -> batch_size x 1 x h x w
    label = Variable(label.long()).cuda()
    criterion = CrossEntropy2d(ignore_label=args.ignore_label).cuda(gpu)

    return criterion(pred, label)


def lr_poly(base_lr, iter, max_iter, power):
    return base_lr * ((1 - float(iter) / max_iter) ** (power))


def adjust_learning_rate(optimizer, i_iter):
    lr = lr_poly(args.learning_rate, i_iter, args.num_steps, args.power)
    optimizer.param_groups[0]['lr'] = lr
    if len(optimizer.param_groups) > 1:
        optimizer.param_groups[1]['lr'] = lr * 10


def adjust_learning_rate_D(optimizer, i_iter):
    lr = lr_poly(args.learning_rate_D, i_iter, args.num_steps, args.power)
    optimizer.param_groups[0]['lr'] = lr
    if len(optimizer.param_groups) > 1:
        optimizer.param_groups[1]['lr'] = lr * 10

def validate(loader, model, interp, writer, epoch, args):
    # print("Validation...")
    # model.eval()
    # data_list = []
    # disp_images = torch.FloatTensor([])
    # for index, batch in enumerate(loader):
    #     if index % 100 == 0:
    #         print('%d processd' % (index))
    #     image, label, _, size = batch
    #     image = image.cuda()
    #     size = size[0].numpy()
    #     output, feature_map = model(image)
    #
    #     output = interp(output)[0]
    #     output = output[:, :size[0], :size[1]]
    #     pred_tensor = torch.argmax(output, dim=0).unsqueeze(0)
    #     pred_tensor = pred_tensor.permute(1, 2, 0)
    #     label_pred = np.asarray(pred_tensor.cpu().detach().numpy(), dtype=np.int)
    #     label = label[:, :size[0], :size[1]]
    #     gt = np.asarray(label[0].numpy(), dtype=np.int)
    #
    #     data_list.append([gt.flatten(), label_pred.flatten()])
    #     if index<10:
    #         disp_images = torch.cat(
    #             [disp_images, torch.cat([15*(label*(label<args.ignore_label)),
    #                                      15*pred_tensor.squeeze().unsqueeze(0).float().cpu()],dim=0)],dim=0)
    #     if index>500: break
    #
    # disp_images = make_grid(disp_images.unsqueeze(1), nrow=2, normalize=True)
    # writer.add_image('validation/'+ key +' segmentation images', disp_images, epoch)
    # meanIOU = get_iou(data_list, args.num_classes)
    # writer.add_scalar('validation/'+ key +' mean IOU', meanIOU, epoch)
    # return meanIOU


    for index, batch in enumerate(loader):
        if index % 100 == 0:
            print('%d processd' % index)
            break
        image, _, name = batch
        output1, output2 = model(Variable(image, volatile=True).cuda())
        output = interp(output2).cpu().data[0].numpy()

        output = output.transpose(1,2,0)
        output = np.asarray(np.argmax(output, axis=2), dtype=np.uint8)

        output_col = colorize_mask(output)
        output = Image.fromarray(output)

        name = name[0].split('/')[-1]
        output.save('%s/%s' % (args.save, name))
        output_col.save('%s/%s_color.png' % (args.save, name.split('.')[0]))

    meanIOU = compute_mIoU(gt_dir = args.data_dir_target.replace('leftImg8bit', 'gtFine/val'),
                           pred_dir = args.save,
                           devkit_dir = 'dataset/cityscapes_list')
    
    writer.add_scalar('validation/cscape mean IOU', meanIOU, epoch)

def main():
    """Create the model and start the training."""

    writer = SummaryWriter('./logs')

    h, w = map(int, args.input_size.split(','))
    input_size = (h, w)

    h, w = map(int, args.input_size_target.split(','))
    input_size_target = (h, w)

    cudnn.enabled = True
    gpu = args.gpu

    # Create network
    if args.model == 'DeepLab':
        model = Res_Deeplab(num_classes=args.num_classes)
        model_state_dict = model.state_dict()
        if args.restore_from[:4] == 'http' :
            saved_state_dict = model_zoo.load_url(args.restore_from)
        elif args.restore_from[:4] == 'https' :
            saved_state_dict = model_zoo.load_url(args.restore_from)
        else:
            saved_state_dict = torch.load(args.restore_from)

        saved_state_dict = {k.replace('Scale.', ''): v for k, v in saved_state_dict.items() if k.replace('Scale.', '')
                      in model_state_dict and 'layer5' not in k }
        # new_params = model.state_dict().copy()
        # for i in saved_state_dict:
        #     # Scale.layer5.conv2d_list.3.weight
        #     i_parts = i.split('.')
        #     # print i_parts
        #     if not args.num_classes == 19 or not i_parts[1] == 'layer5':
        #         print('.'.join(i_parts[1:]),saved_state_dict[i])
        #         # print i_parts
        # print("Key new")
        # print(new_params.keys())
        # print("your model new")
        # print(saved_state_dict.keys())
        model_state_dict.update(saved_state_dict)
        model.load_state_dict(model_state_dict)

    # model = torch.nn.DataParallel(model)
    # patch_replication_callback(model)
    model.train()
    model.cuda(args.gpu)

    cudnn.benchmark = True

    # # init D
    # model_D1 = FCDiscriminator(num_classes=args.num_classes)
    # model_D2 = FCDiscriminator(num_classes=args.num_classes)
    #
    # # model_D1 = torch.nn.DataParallel(model_D1)
    # # patch_replication_callback(model_D1)
    # model_D1.train()
    # model_D1.cuda(args.gpu)
    #
    # # model_D2 = torch.nn.DataParallel(model_D2)
    # # patch_replication_callback(model_D2)
    # model_D2.train()
    # model_D2.cuda(args.gpu)

    if not os.path.exists(args.snapshot_dir):
        os.makedirs(args.snapshot_dir)

    trainloader = data.DataLoader(
        SynthiaDataSet(args.data_dir, args.data_list, max_iters=args.num_steps * args.iter_size * args.batch_size,
                    crop_size=input_size,
                    scale=args.random_scale, mirror=args.random_mirror, mean=IMG_MEAN),
        batch_size=args.batch_size, shuffle=True, num_workers=args.num_workers, pin_memory=True)

    trainloader_iter = enumerate(trainloader)

    targetloader = data.DataLoader(cityscapesDataSet(args.data_dir_target, args.data_list_target,
                                                     max_iters=args.num_steps * args.iter_size * args.batch_size,
                                                     crop_size=input_size_target,
                                                     scale=False, mirror=args.random_mirror, mean=IMG_MEAN,
                                                     set=args.set),
                                   batch_size=args.batch_size, shuffle=True, num_workers=args.num_workers,
                                   pin_memory=True)


    targetloader_iter = enumerate(targetloader)

    targetloader_val = data.DataLoader(
        cityscapesDataSet(args.data_dir_target, args.data_list_target.replace('train.txt', 'val.txt'),
                          crop_size=(1024, 512), mean=IMG_MEAN, scale=False, mirror=False, set='val'),
        batch_size=1, shuffle=False,pin_memory=True)

    # implement model.optim_parameters(args) to handle different models' lr setting

    optimizer = optim.SGD(model.optim_parameters(args),
                          lr=args.learning_rate, momentum=args.momentum, weight_decay=args.weight_decay)
    optimizer.zero_grad()

    # optimizer_D1 = optim.Adam(model_D1.parameters(), lr=args.learning_rate_D, betas=(0.9, 0.99))
    # optimizer_D1.zero_grad()
    #
    # optimizer_D2 = optim.Adam(model_D2.parameters(), lr=args.learning_rate_D, betas=(0.9, 0.99))
    # optimizer_D2.zero_grad()

    bce_loss = torch.nn.BCEWithLogitsLoss()

    interp = nn.Upsample(size=(input_size[1], input_size[0]), mode='bilinear')
    interp_target = nn.Upsample(size=(1024, 2048), mode='bilinear')

    # labels for adversarial training
    source_label = 0
    target_label = 1

    for i_iter in range(args.num_steps):

        ipdb.set_trace()

        if i_iter%(len(trainloader_iter)*args.batch_size)==0:
            validate(targetloader_val, model, interp_target, writer, i_iter, args)


        loss_seg_value1 = 0
        loss_adv_target_value1 = 0
        loss_D_value1 = 0

        loss_seg_value2 = 0
        loss_adv_target_value2 = 0
        loss_D_value2 = 0

        optimizer.zero_grad()
        adjust_learning_rate(optimizer, i_iter)

        # optimizer_D1.zero_grad()
        # optimizer_D2.zero_grad()
        # adjust_learning_rate_D(optimizer_D1, i_iter)
        # adjust_learning_rate_D(optimizer_D2, i_iter)

        for sub_i in range(args.iter_size):

            # train G

            # # don't accumulate grads in D
            # for param in model_D1.parameters():
            #     param.requires_grad = False
            #
            # for param in model_D2.parameters():
            #     param.requires_grad = False

            # train with source
            _, batch = next(trainloader_iter)
            images, labels, _, _ = batch
            images = Variable(images).cuda(args.gpu)

            pred1, pred2 = model(images)
            pred1 = interp(pred1)
            pred2 = interp(pred2)

            loss_seg1 = loss_calc(pred1, labels, args.gpu)
            loss_seg2 = loss_calc(pred2, labels, args.gpu)
            loss = loss_seg2 + args.lambda_seg * loss_seg1

            # proper normalization
            loss = loss / args.iter_size
            loss.backward()
            loss_seg_value1 += loss_seg1.item() / args.iter_size
            loss_seg_value2 += loss_seg2.item() / args.iter_size

            # # train with target
            #
            # _, batch = next(targetloader_iter)
            # images, _, _ = batch
            # images = Variable(images).cuda(args.gpu)
            #
            # pred_target1, pred_target2 = model(images)
            # pred_target1 = interp_target(pred_target1)
            # pred_target2 = interp_target(pred_target2)
            #
            # D_out1 = model_D1(F.softmax(pred_target1))
            # D_out2 = model_D2(F.softmax(pred_target2))
            #
            # loss_adv_target1 = bce_loss(D_out1,
            #                            Variable(torch.FloatTensor(D_out1.data.size()).fill_(source_label)).cuda(
            #                                args.gpu))
            #
            # loss_adv_target2 = bce_loss(D_out2,
            #                             Variable(torch.FloatTensor(D_out2.data.size()).fill_(source_label)).cuda(
            #                                 args.gpu))
            #
            # loss = args.lambda_adv_target1 * loss_adv_target1 + args.lambda_adv_target2 * loss_adv_target2
            # loss = loss / args.iter_size
            # loss.backward()
            # loss_adv_target_value1 += loss_adv_target1.data.cpu().numpy()[0] / args.iter_size
            # loss_adv_target_value2 += loss_adv_target2.data.cpu().numpy()[0] / args.iter_size

            # # train D
            #
            # # bring back requires_grad
            # for param in model_D1.parameters():
            #     param.requires_grad = True
            #
            # for param in model_D2.parameters():
            #     param.requires_grad = True
            #
            # # train with source
            # pred1 = pred1.detach()
            # pred2 = pred2.detach()
            #
            # D_out1 = model_D1(F.softmax(pred1))
            # D_out2 = model_D2(F.softmax(pred2))
            #
            # loss_D1 = bce_loss(D_out1,
            #                   Variable(torch.FloatTensor(D_out1.data.size()).fill_(source_label)).cuda(args.gpu))
            #
            # loss_D2 = bce_loss(D_out2,
            #                    Variable(torch.FloatTensor(D_out2.data.size()).fill_(source_label)).cuda(args.gpu))
            #
            # loss_D1 = loss_D1 / args.iter_size / 2
            # loss_D2 = loss_D2 / args.iter_size / 2
            #
            # loss_D1.backward()
            # loss_D2.backward()
            #
            # loss_D_value1 += loss_D1.data.cpu().numpy()[0]
            # loss_D_value2 += loss_D2.data.cpu().numpy()[0]
            #
            # # train with target
            # pred_target1 = pred_target1.detach()
            # pred_target2 = pred_target2.detach()
            #
            # D_out1 = model_D1(F.softmax(pred_target1))
            # D_out2 = model_D2(F.softmax(pred_target2))
            #
            # loss_D1 = bce_loss(D_out1,
            #                   Variable(torch.FloatTensor(D_out1.data.size()).fill_(target_label)).cuda(args.gpu))
            #
            # loss_D2 = bce_loss(D_out2,
            #                    Variable(torch.FloatTensor(D_out2.data.size()).fill_(target_label)).cuda(args.gpu))
            #
            # loss_D1 = loss_D1 / args.iter_size / 2
            # loss_D2 = loss_D2 / args.iter_size / 2
            #
            # loss_D1.backward()
            # loss_D2.backward()
            #
            # loss_D_value1 += loss_D1.data.cpu().numpy()[0]
            # loss_D_value2 += loss_D2.data.cpu().numpy()[0]

        optimizer.step()
        # optimizer_D1.step()
        # optimizer_D2.step()

        print('exp = {}'.format(args.snapshot_dir))
        print(
        'iter = {0:8d}/{1:8d}, loss_seg1 = {2:.3f} loss_seg2 = {3:.3f} loss_adv1 = {4:.3f}, loss_adv2 = {5:.3f} loss_D1 = {6:.3f} loss_D2 = {7:.3f}'.format(
            i_iter, args.num_steps, loss_seg_value1, loss_seg_value2, loss_adv_target_value1, loss_adv_target_value2, loss_D_value1, loss_D_value2))

        if i_iter >= args.num_steps_stop - 1:
            print ('save model ...')
            torch.save(model.state_dict(), osp.join(args.snapshot_dir, 'Synthia_' + str(args.num_steps) + '.pth'))
            torch.save(model_D1.state_dict(), osp.join(args.snapshot_dir, 'Synthia_' + str(args.num_steps) + '_D1.pth'))
            torch.save(model_D2.state_dict(), osp.join(args.snapshot_dir, 'Synthia_' + str(args.num_steps) + '_D2.pth'))
            break

        if i_iter % args.save_pred_every == 0 and i_iter != 0:
            print ('taking snapshot ...')
            torch.save(model.state_dict(), osp.join(args.snapshot_dir, 'Synthia_' + str(i_iter) + '.pth'))
            torch.save(model_D1.state_dict(), osp.join(args.snapshot_dir, 'Synthia_' + str(i_iter) + '_D1.pth'))
            torch.save(model_D2.state_dict(), osp.join(args.snapshot_dir, 'Synthia_' + str(i_iter) + '_D2.pth'))


if __name__ == '__main__':
    main()
