"""Network definitions for the fix-in-post pack (fix_worker.py loads weights into these; torch only, no other deps).

SCUNet: from https://github.com/cszn/SCUNet (models/network_scunet.py), Copyright (c) Kai Zhang et al.,
        Apache License 2.0 (C:\\LetItEdit\\models\\scunet\\LICENSE.txt). Changes: thop/timm imports removed
        (DropPath -> Identity at inference, no init), prints removed, relative index cached.
RRDBNet, SRVGGNetCompact: re-implemented after BasicSR (Apache-2.0, https://github.com/XPixelGroup/BasicSR) and
        Real-ESRGAN (BSD-3-Clause, https://github.com/xinntao/Real-ESRGAN) so their released weights load.
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from einops import rearrange


# ------------------------------------------------------------------ SCUNet (Apache-2.0)

class WMSA(nn.Module):
    def __init__(self, input_dim, output_dim, head_dim, window_size, type):
        super().__init__()
        self.input_dim = input_dim
        self.output_dim = output_dim
        self.head_dim = head_dim
        self.scale = self.head_dim ** -0.5
        self.n_heads = input_dim // head_dim
        self.window_size = window_size
        self.type = type
        self.embedding_layer = nn.Linear(self.input_dim, 3 * self.input_dim, bias=True)
        p = torch.zeros((2 * window_size - 1) * (2 * window_size - 1), self.n_heads)
        self.relative_position_params = nn.Parameter(
            p.view(2 * window_size - 1, 2 * window_size - 1, self.n_heads).transpose(1, 2).transpose(0, 1))
        self.linear = nn.Linear(self.input_dim, self.output_dim)
        cord = torch.tensor(np.array([[i, j] for i in range(window_size) for j in range(window_size)]))
        self.register_buffer('relation', (cord[:, None, :] - cord[None, :, :] + window_size - 1).long(), persistent=False)

    def generate_mask(self, h, w, p, shift):
        attn_mask = torch.zeros(h, w, p, p, p, p, dtype=torch.bool, device=self.relative_position_params.device)
        if self.type == 'W':
            return attn_mask
        s = p - shift
        attn_mask[-1, :, :s, :, s:, :] = True
        attn_mask[-1, :, s:, :, :s, :] = True
        attn_mask[:, -1, :, :s, :, s:] = True
        attn_mask[:, -1, :, s:, :, :s] = True
        return rearrange(attn_mask, 'w1 w2 p1 p2 p3 p4 -> 1 1 (w1 w2) (p1 p2) (p3 p4)')

    def forward(self, x):
        if self.type != 'W':
            x = torch.roll(x, shifts=(-(self.window_size // 2), -(self.window_size // 2)), dims=(1, 2))
        x = rearrange(x, 'b (w1 p1) (w2 p2) c -> b w1 w2 p1 p2 c', p1=self.window_size, p2=self.window_size)
        h_windows, w_windows = x.size(1), x.size(2)
        x = rearrange(x, 'b w1 w2 p1 p2 c -> b (w1 w2) (p1 p2) c', p1=self.window_size, p2=self.window_size)
        qkv = self.embedding_layer(x)
        q, k, v = rearrange(qkv, 'b nw np (threeh c) -> threeh b nw np c', c=self.head_dim).chunk(3, dim=0)
        sim = torch.einsum('hbwpc,hbwqc->hbwpq', q, k) * self.scale
        rel = self.relative_position_params[:, self.relation[:, :, 0], self.relation[:, :, 1]]
        sim = sim + rearrange(rel, 'h p q -> h 1 1 p q')
        if self.type != 'W':
            attn_mask = self.generate_mask(h_windows, w_windows, self.window_size, shift=self.window_size // 2)
            sim = sim.masked_fill_(attn_mask, float('-inf'))
        probs = F.softmax(sim, dim=-1)
        output = torch.einsum('hbwij,hbwjc->hbwic', probs, v)
        output = rearrange(output, 'h b w p c -> b w p (h c)')
        output = self.linear(output)
        output = rearrange(output, 'b (w1 w2) (p1 p2) c -> b (w1 p1) (w2 p2) c', w1=h_windows, p1=self.window_size)
        if self.type != 'W':
            output = torch.roll(output, shifts=(self.window_size // 2, self.window_size // 2), dims=(1, 2))
        return output


class Block(nn.Module):
    def __init__(self, input_dim, output_dim, head_dim, window_size, type='W', input_resolution=None):
        super().__init__()
        self.type = 'W' if input_resolution <= window_size else type
        self.ln1 = nn.LayerNorm(input_dim)
        self.msa = WMSA(input_dim, input_dim, head_dim, window_size, self.type)
        self.ln2 = nn.LayerNorm(input_dim)
        self.mlp = nn.Sequential(nn.Linear(input_dim, 4 * input_dim), nn.GELU(), nn.Linear(4 * input_dim, output_dim))

    def forward(self, x):
        x = x + self.msa(self.ln1(x))
        return x + self.mlp(self.ln2(x))


class ConvTransBlock(nn.Module):
    def __init__(self, conv_dim, trans_dim, head_dim, window_size, type='W', input_resolution=None):
        super().__init__()
        self.conv_dim, self.trans_dim = conv_dim, trans_dim
        if input_resolution <= window_size:
            type = 'W'
        self.trans_block = Block(trans_dim, trans_dim, head_dim, window_size, type, input_resolution)
        self.conv1_1 = nn.Conv2d(conv_dim + trans_dim, conv_dim + trans_dim, 1, 1, 0, bias=True)
        self.conv1_2 = nn.Conv2d(conv_dim + trans_dim, conv_dim + trans_dim, 1, 1, 0, bias=True)
        self.conv_block = nn.Sequential(nn.Conv2d(conv_dim, conv_dim, 3, 1, 1, bias=False), nn.ReLU(True),
                                        nn.Conv2d(conv_dim, conv_dim, 3, 1, 1, bias=False))

    def forward(self, x):
        conv_x, trans_x = torch.split(self.conv1_1(x), (self.conv_dim, self.trans_dim), dim=1)
        conv_x = self.conv_block(conv_x) + conv_x
        trans_x = rearrange(trans_x, 'b c h w -> b h w c')
        trans_x = rearrange(self.trans_block(trans_x), 'b h w c -> b c h w')
        return x + self.conv1_2(torch.cat((conv_x, trans_x), dim=1))


class SCUNet(nn.Module):
    def __init__(self, in_nc=3, config=(4, 4, 4, 4, 4, 4, 4), dim=64, input_resolution=256):
        super().__init__()
        hd, ws = 32, 8
        t = lambda i: 'W' if not i % 2 else 'SW'  # noqa: E731
        self.m_head = nn.Sequential(nn.Conv2d(in_nc, dim, 3, 1, 1, bias=False))
        self.m_down1 = nn.Sequential(*[ConvTransBlock(dim // 2, dim // 2, hd, ws, t(i), input_resolution) for i in range(config[0])],
                                     nn.Conv2d(dim, 2 * dim, 2, 2, 0, bias=False))
        self.m_down2 = nn.Sequential(*[ConvTransBlock(dim, dim, hd, ws, t(i), input_resolution // 2) for i in range(config[1])],
                                     nn.Conv2d(2 * dim, 4 * dim, 2, 2, 0, bias=False))
        self.m_down3 = nn.Sequential(*[ConvTransBlock(2 * dim, 2 * dim, hd, ws, t(i), input_resolution // 4) for i in range(config[2])],
                                     nn.Conv2d(4 * dim, 8 * dim, 2, 2, 0, bias=False))
        self.m_body = nn.Sequential(*[ConvTransBlock(4 * dim, 4 * dim, hd, ws, t(i), input_resolution // 8) for i in range(config[3])])
        self.m_up3 = nn.Sequential(nn.ConvTranspose2d(8 * dim, 4 * dim, 2, 2, 0, bias=False),
                                   *[ConvTransBlock(2 * dim, 2 * dim, hd, ws, t(i), input_resolution // 4) for i in range(config[4])])
        self.m_up2 = nn.Sequential(nn.ConvTranspose2d(4 * dim, 2 * dim, 2, 2, 0, bias=False),
                                   *[ConvTransBlock(dim, dim, hd, ws, t(i), input_resolution // 2) for i in range(config[5])])
        self.m_up1 = nn.Sequential(nn.ConvTranspose2d(2 * dim, dim, 2, 2, 0, bias=False),
                                   *[ConvTransBlock(dim // 2, dim // 2, hd, ws, t(i), input_resolution) for i in range(config[6])])
        self.m_tail = nn.Sequential(nn.Conv2d(dim, in_nc, 3, 1, 1, bias=False))

    def forward(self, x0):
        h, w = x0.size()[-2:]
        pb, pr = int(np.ceil(h / 64) * 64 - h), int(np.ceil(w / 64) * 64 - w)
        x0 = nn.ReplicationPad2d((0, pr, 0, pb))(x0)
        x1 = self.m_head(x0)
        x2 = self.m_down1(x1)
        x3 = self.m_down2(x2)
        x4 = self.m_down3(x3)
        x = self.m_body(x4)
        x = self.m_up3(x + x4)
        x = self.m_up2(x + x3)
        x = self.m_up1(x + x2)
        x = self.m_tail(x + x1)
        return x[..., :h, :w]


# ------------------------------------------------------------------ RRDBNet (Real-ESRGAN x2plus / x4plus)

class ResidualDenseBlock(nn.Module):
    def __init__(self, nf=64, gc=32):
        super().__init__()
        self.conv1 = nn.Conv2d(nf, gc, 3, 1, 1)
        self.conv2 = nn.Conv2d(nf + gc, gc, 3, 1, 1)
        self.conv3 = nn.Conv2d(nf + 2 * gc, gc, 3, 1, 1)
        self.conv4 = nn.Conv2d(nf + 3 * gc, gc, 3, 1, 1)
        self.conv5 = nn.Conv2d(nf + 4 * gc, nf, 3, 1, 1)
        self.lrelu = nn.LeakyReLU(0.2, inplace=True)

    def forward(self, x):
        x1 = self.lrelu(self.conv1(x))
        x2 = self.lrelu(self.conv2(torch.cat((x, x1), 1)))
        x3 = self.lrelu(self.conv3(torch.cat((x, x1, x2), 1)))
        x4 = self.lrelu(self.conv4(torch.cat((x, x1, x2, x3), 1)))
        x5 = self.conv5(torch.cat((x, x1, x2, x3, x4), 1))
        return x5 * 0.2 + x


class RRDB(nn.Module):
    def __init__(self, nf, gc=32):
        super().__init__()
        self.rdb1 = ResidualDenseBlock(nf, gc)
        self.rdb2 = ResidualDenseBlock(nf, gc)
        self.rdb3 = ResidualDenseBlock(nf, gc)

    def forward(self, x):
        return self.rdb3(self.rdb2(self.rdb1(x))) * 0.2 + x


class RRDBNet(nn.Module):
    def __init__(self, num_in_ch=3, num_out_ch=3, scale=4, num_feat=64, num_block=23, num_grow_ch=32):
        super().__init__()
        self.scale = scale
        if scale == 2:
            num_in_ch *= 4
        elif scale == 1:
            num_in_ch *= 16
        self.conv_first = nn.Conv2d(num_in_ch, num_feat, 3, 1, 1)
        self.body = nn.Sequential(*[RRDB(num_feat, num_grow_ch) for _ in range(num_block)])
        self.conv_body = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_up1 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_up2 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_hr = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_last = nn.Conv2d(num_feat, num_out_ch, 3, 1, 1)
        self.lrelu = nn.LeakyReLU(0.2, inplace=True)

    def forward(self, x):
        if self.scale == 2:
            feat = F.pixel_unshuffle(x, 2)
        elif self.scale == 1:
            feat = F.pixel_unshuffle(x, 4)
        else:
            feat = x
        feat = self.conv_first(feat)
        feat = feat + self.conv_body(self.body(feat))
        feat = self.lrelu(self.conv_up1(F.interpolate(feat, scale_factor=2, mode='nearest')))
        feat = self.lrelu(self.conv_up2(F.interpolate(feat, scale_factor=2, mode='nearest')))
        return self.conv_last(self.lrelu(self.conv_hr(feat)))


# ------------------------------------------------------------------ SRVGGNetCompact (realesr-general-x4v3)

class SRVGGNetCompact(nn.Module):
    def __init__(self, num_in_ch=3, num_out_ch=3, num_feat=64, num_conv=32, upscale=4):
        super().__init__()
        self.upscale = upscale
        body = [nn.Conv2d(num_in_ch, num_feat, 3, 1, 1), nn.PReLU(num_parameters=num_feat)]
        for _ in range(num_conv):
            body += [nn.Conv2d(num_feat, num_feat, 3, 1, 1), nn.PReLU(num_parameters=num_feat)]
        body.append(nn.Conv2d(num_feat, num_out_ch * upscale * upscale, 3, 1, 1))
        self.body = nn.ModuleList(body)
        self.upsampler = nn.PixelShuffle(upscale)

    def forward(self, x):
        out = x
        for m in self.body:
            out = m(out)
        out = self.upsampler(out)
        return out + F.interpolate(x, scale_factor=self.upscale, mode='nearest')
