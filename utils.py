import torch
import torch.nn as nn
from torchvision.models import densenet169, resnet50
import torchvision.transforms as transforms
from efficientnet_pytorch import EfficientNet
from resnest.torch import resnest50
import numpy as np

class Efficient_head(nn.Module):
    def __init__(self, pre_model, n_kps=7):
        super(Efficient_head, self).__init__()
        self.pre_model = pre_model
        self.last_conv = nn.Conv2d(120, 3*n_kps, (1,1), 1)
        self.output = nn.Sigmoid()
        for block in self.pre_model._blocks[16:]:
            block = nn.Identity()
        self.pre_model._conv_head = nn.Identity()
        self.pre_model._bn1 = nn.Identity()
        self.pre_model._avg_pooling = nn.Identity()
        self.pre_model._dropout = nn.Identity()
        self.pre_model._fc = nn.Identity()
    def forward(self, x):
        x = self.pre_model._conv_stem(x)
        x = self.pre_model._bn0(x)
        for block in self.pre_model._blocks[:16]:
          x = block(x)
        x = self.last_conv(x)
        x = self.output(x)
        return x

class ResNeSt_head(nn.Module):
    def __init__(self, pre_model, n_kps):
        super(ResNeSt_head, self).__init__()
        self.pre_model = pre_model
        self.pre_model.fc = nn.Identity()
        self.pre_model.avgpool = nn.Identity()
        self.pre_model.layer4 = nn.Identity()
        self.last_conv = nn.Conv2d(1024, 3*n_kps, (1,1), 1)
        self.output = nn.Sigmoid()
    def forward(self, x):
        x = self.pre_model.conv1(x)
        x = self.pre_model.bn1(x)
        x = self.pre_model.relu(x)
        x = self.pre_model.maxpool(x)
        x = self.pre_model.layer1(x)
        x = self.pre_model.layer2(x)
        x = self.pre_model.layer3(x)
        x = self.last_conv(x)
        x = self.output(x)
        return x

def build_detection_based_model(model_name, n_kps=7, pretrained=True):
  if model_name == 'efficient':
    pre_model = EfficientNet.from_pretrained('efficientnet-b2')
    for param in pre_model.parameters():
        param.requires_grad = True
    model = Efficient_head(pre_model, n_kps)
    return model
  elif model_name == 'resnest':
    pre_model = resnest50(pretrained=pretrained)
    for param in pre_model.parameters():
        param.requires_grad = True
    model = ResNeSt_head(pre_model, n_kps)
    return model
  else:
    print('Not support this model!')

def build_regression_based_model(model_name, n_kps=7, pretrained=True):
    if model_name == 'efficient':
        model = EfficientNet.from_pretrained('efficientnet-b2')
        for param in model.parameters():
            param.requires_grad = True
        in_feature = model._fc.in_features
        model._fc = nn.Sequential(nn.Linear(in_feature, 2*n_kps, bias=True), nn.Sigmoid())
        return model 
    elif model_name == 'resnest':
        model = resnest50(pretrained=pretrained)
        for param in model.parameters():
            param.requires_grad = True
        in_feature = model.fc.in_features
        model.fc = nn.Sequential(nn.Linear(in_feature, 2*n_kps, bias=True), nn.Sigmoid())
        return model
    else:
        print('Not support this model!')

def preprocessed_img_test(img, img_size):
    trans = transforms.Compose([transforms.ToPILImage(),
                                transforms.Resize(img_size[:2]),
                                transforms.ToTensor()
    ])
    oh, ow = img.shape[:2]
    if oh > ow:
        new_img = np.zeros((oh, oh, 3), np.uint8)
        cl = ((oh-ow)//2)
        new_img[:,cl:cl+ow] = img
        clx = cl
        cly = 0
    else:
        new_img = np.zeros((ow, ow, 3), np.uint8)
        cl = ((ow-oh)//2)
        new_img[cl:cl+oh,:] = img
        clx = 0
        cly = cl
    new_img = trans(new_img)
    new_img = torch.unsqueeze(new_img, 0)
    return new_img, max([oh, ow]), clx, cly

def heatmap2coor(hp_preds, n_kps = 7, img_size=(225,225), stride=15):
    heatmaps = hp_preds[:,:n_kps]
    flatten_hm = heatmaps.reshape((heatmaps.shape[0], n_kps, -1))
    flat_vectx = hp_preds[:,n_kps:2*n_kps].reshape((heatmaps.shape[0], n_kps, -1))
    flat_vecty = hp_preds[:,2*n_kps:].reshape((heatmaps.shape[0], n_kps, -1))
    flat_max = torch.argmax(flatten_hm, dim=-1)
    max_mask = flatten_hm == torch.unsqueeze(torch.max(flatten_hm, dim=-1)[0], dim=-1)
    cxs = flat_max%(heatmaps.shape[-2])
    cys = flat_max//(heatmaps.shape[-2])
    ovxs = torch.sum(flat_vectx*max_mask, dim=-1)*stride
    ovys = torch.sum(flat_vecty*max_mask, dim=-1)*stride
    xs_p = (cxs*stride+ovxs)/img_size[1]
    ys_p = (cys*stride+ovys)/img_size[0]
    hp_preds = torch.stack([xs_p, ys_p], dim=-1)
    return hp_preds