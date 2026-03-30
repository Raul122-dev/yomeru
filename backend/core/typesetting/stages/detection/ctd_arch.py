"""
CTD blk_det model architecture — reconstructed from comictextdetector.pt cfg.

Parameters from cfg:
  nc             = 2
  width_multiple = 0.5  (YOLOv5s, NOT YOLOv5n which is 0.25)
  depth_multiple = 0.33
  anchors        = [[10,13,16,30,33,23],[30,61,62,45,59,119],[116,90,156,198,373,326]]

Source: dmMaze/comic-text-detector checkpoint format.
"""
from __future__ import annotations
import math
import torch
import torch.nn as nn


def _autopad(k, p=None):
    return k // 2 if p is None else p


class Conv(nn.Module):
    def __init__(self, c1, c2, k=1, s=1, p=None, g=1, act=True):
        super().__init__()
        self.conv = nn.Conv2d(c1, c2, k, s, _autopad(k, p), groups=g, bias=False)
        self.bn   = nn.BatchNorm2d(c2)
        self.act  = nn.SiLU() if act is True else (act if isinstance(act, nn.Module) else nn.Identity())

    def forward(self, x):
        return self.act(self.bn(self.conv(x)))


class Bottleneck(nn.Module):
    def __init__(self, c1, c2, shortcut=True, g=1, e=0.5):
        super().__init__()
        c_ = int(c2 * e)
        self.cv1 = Conv(c1, c_, 1, 1)
        self.cv2 = Conv(c_, c2, 3, 1, g=g)
        self.add = shortcut and c1 == c2

    def forward(self, x):
        return x + self.cv2(self.cv1(x)) if self.add else self.cv2(self.cv1(x))


class C3(nn.Module):
    def __init__(self, c1, c2, n=1, shortcut=True, g=1, e=0.5):
        super().__init__()
        c_ = int(c2 * e)
        self.cv1 = Conv(c1, c_, 1, 1)
        self.cv2 = Conv(c1, c_, 1, 1)
        self.cv3 = Conv(2 * c_, c2, 1)
        self.m   = nn.Sequential(*[Bottleneck(c_, c_, shortcut, g, e=1.0) for _ in range(n)])

    def forward(self, x):
        return self.cv3(torch.cat((self.m(self.cv1(x)), self.cv2(x)), 1))


class SPPF(nn.Module):
    def __init__(self, c1, c2, k=5):
        super().__init__()
        c_ = c1 // 2
        self.cv1 = Conv(c1, c_, 1, 1)
        self.cv2 = Conv(c_ * 4, c2, 1, 1)
        self.m   = nn.MaxPool2d(kernel_size=k, stride=1, padding=k // 2)

    def forward(self, x):
        x = self.cv1(x)
        y1 = self.m(x)
        y2 = self.m(y1)
        return self.cv2(torch.cat([x, y1, y2, self.m(y2)], 1))


class Concat(nn.Module):
    def __init__(self, dim=1):
        super().__init__()
        self.d = dim

    def forward(self, x: list) -> torch.Tensor:
        return torch.cat(x, self.d)


class Detect(nn.Module):
    def __init__(self, nc=2, anchors=(), ch=()):
        super().__init__()
        self.nc  = nc
        self.no  = nc + 5
        self.nl  = len(anchors)
        self.na  = len(anchors[0]) // 2
        self.grid       = [torch.zeros(1)] * self.nl
        self.anchor_grid = [torch.zeros(1)] * self.nl
        self.register_buffer("anchors", torch.tensor(anchors).float().view(self.nl, -1, 2))
        self.m = nn.ModuleList(nn.Conv2d(x, self.no * self.na, 1) for x in ch)

    def forward(self, x: list) -> tuple:
        z = []
        for i in range(self.nl):
            x[i] = self.m[i](x[i])
            bs, _, ny, nx = x[i].shape
            x[i] = x[i].view(bs, self.na, self.no, ny, nx).permute(0, 1, 3, 4, 2).contiguous()
            if not self.training:
                if self.grid[i].shape[2:4] != x[i].shape[2:4]:
                    self.grid[i], self.anchor_grid[i] = self._make_grid(nx, ny, i)
                y = x[i].sigmoid()
                y[..., 0:2] = (y[..., 0:2] * 2 - 0.5 + self.grid[i]) * self.stride[i]
                y[..., 2:4] = (y[..., 2:4] * 2) ** 2 * self.anchor_grid[i]
                z.append(y.view(bs, -1, self.no))
        # In training mode z is empty — return raw x for stride inference
        return (torch.cat(z, 1) if z else x[0], x)

    def _make_grid(self, nx, ny, i):
        d  = self.anchors[i].device
        yv, xv = torch.meshgrid(
            [torch.arange(ny, device=d), torch.arange(nx, device=d)], indexing="ij"
        )
        grid        = torch.stack((xv, yv), 2).expand(1, self.na, ny, nx, 2).float()
        anchor_grid = (self.anchors[i].clone() * self.stride[i]).view(1, self.na, 1, 1, 2).expand(1, self.na, ny, nx, 2).float()
        return grid, anchor_grid


# ── Main model ────────────────────────────────────────────────────────────────

_ANCHORS = [
    [10, 13, 16, 30, 33, 23],
    [30, 61, 62, 45, 59, 119],
    [116, 90, 156, 198, 373, 326],
]


class CTDBlkDet(nn.Module):
    """
    CTD block detector reconstructed from comictextdetector.pt cfg.
    width_multiple=0.5 (YOLOv5s), depth_multiple=0.33, nc=2.

    Layer indices match the checkpoint's state_dict keys (model.N.*).
    Concat layers (12, 16, 19, 22) have no weights and are skipped in state_dict.
    """

    def __init__(self, nc: int = 2):
        super().__init__()
        gw, gd = 0.5, 0.33

        def ch(c: int) -> int:
            return int(c * gw)

        def n(x: int) -> int:
            return max(round(x * gd), 1)

        # ch values at each width: 32, 64, 128, 256, 512
        c0, c1, c2, c3, c4 = ch(64), ch(128), ch(256), ch(512), ch(1024)
        # = 32,  64,  128,  256,  512

        # All 25 layers stored in ModuleList to match state_dict indices.
        # Concat layers have no parameters; they act as placeholder modules.
        self.model = nn.ModuleList([
            # ── backbone (0-9) ────────────────────────────────────────────
            Conv(3, c0, 6, 2, 2),          # 0  → 32ch  P1/2
            Conv(c0, c1, 3, 2),            # 1  → 64ch  P2/4
            C3(c1, c1, n(3)),              # 2  → 64ch
            Conv(c1, c2, 3, 2),            # 3  → 128ch P3/8
            C3(c2, c2, n(6)),              # 4  → 128ch
            Conv(c2, c3, 3, 2),            # 5  → 256ch P4/16
            C3(c3, c3, n(9)),              # 6  → 256ch
            Conv(c3, c4, 3, 2),            # 7  → 512ch P5/32
            C3(c4, c4, n(3)),              # 8  → 512ch
            SPPF(c4, c4, 5),              # 9  → 512ch

            # ── head (10-24) ──────────────────────────────────────────────
            Conv(c4, c3, 1, 1),           # 10 → 256ch
            nn.Upsample(scale_factor=2, mode="nearest"),  # 11
            Concat(1),                    # 12 cat(11, 6) → 256+256=512ch
            C3(c3 * 2, c3, n(3), shortcut=False),  # 13 → 256ch
            Conv(c3, c2, 1, 1),           # 14 → 128ch
            nn.Upsample(scale_factor=2, mode="nearest"),  # 15
            Concat(1),                    # 16 cat(15, 4) → 128+128=256ch
            C3(c2 * 2, c2, n(3), shortcut=False),  # 17 → 128ch  ← P3 detect
            Conv(c2, c2, 3, 2),           # 18 → 128ch
            Concat(1),                    # 19 cat(18, 14) → 128+128=256ch
            C3(c2 * 2, c3, n(3), shortcut=False),  # 20 → 256ch  ← P4 detect
            Conv(c3, c3, 3, 2),           # 21 → 256ch
            Concat(1),                    # 22 cat(21, 10) → 256+256=512ch
            C3(c3 * 2, c4, n(3), shortcut=False),  # 23 → 512ch  ← P5 detect
            Detect(nc, _ANCHORS, ch=(c2, c3, c4)),  # 24 from [17, 20, 23]
        ])

        # Compute strides for Detect decode.
        # Run in training mode — forward returns (x[0], x) where x has the
        # per-scale feature tensors whose shapes give us the strides.
        detect = self.model[24]
        assert isinstance(detect, Detect)
        s = 256
        with torch.no_grad():
            _, feat = self.forward(torch.zeros(1, 3, s, s))
        # feat[i] shape: [bs, na, ny, nx, no] — stride = s / ny
        detect.stride = torch.tensor([s / f.shape[2] for f in feat])
        detect.anchors /= detect.stride.view(-1, 1, 1)

    def forward(self, x: torch.Tensor) -> tuple:
        y: list = [None] * len(self.model)

        y[0]  = self.model[0](x)
        y[1]  = self.model[1](y[0])
        y[2]  = self.model[2](y[1])
        y[3]  = self.model[3](y[2])
        y[4]  = self.model[4](y[3])   # P3 128ch
        y[5]  = self.model[5](y[4])
        y[6]  = self.model[6](y[5])   # P4 256ch
        y[7]  = self.model[7](y[6])
        y[8]  = self.model[8](y[7])
        y[9]  = self.model[9](y[8])   # SPPF 512ch

        y[10] = self.model[10](y[9])  # Conv → 256ch
        y[11] = self.model[11](y[10]) # Upsample
        y[12] = self.model[12]([y[11], y[6]])   # Concat → 512ch
        y[13] = self.model[13](y[12])
        y[14] = self.model[14](y[13]) # Conv → 128ch
        y[15] = self.model[15](y[14]) # Upsample
        y[16] = self.model[16]([y[15], y[4]])   # Concat → 256ch
        y[17] = self.model[17](y[16]) # C3 → 128ch  (P3 head)
        y[18] = self.model[18](y[17]) # Conv → 128ch
        y[19] = self.model[19]([y[18], y[14]])  # Concat → 256ch
        y[20] = self.model[20](y[19]) # C3 → 256ch  (P4 head)
        y[21] = self.model[21](y[20]) # Conv → 256ch
        y[22] = self.model[22]([y[21], y[10]])  # Concat → 512ch
        y[23] = self.model[23](y[22]) # C3 → 512ch  (P5 head)
        y[24] = self.model[24]([y[17], y[20], y[23]])  # Detect

        return y[24]