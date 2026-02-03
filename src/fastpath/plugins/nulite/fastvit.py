from typing import List, Tuple

import torch
import torch.nn as nn
import timm


class FastViTEncoder(nn.Module):

    def __init__(self, vit_structure: str, pretrained: bool = False) -> None:
        super().__init__()

        self.fast_vit = timm.create_model(
            f"{vit_structure}.apple_in1k",
            features_only=True,
            pretrained=pretrained
        )

        self.avg_pooling = nn.Sequential(nn.AdaptiveAvgPool2d((1, 1)), nn.Flatten())

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, List[torch.Tensor]]:
        extracted_layers = self.fast_vit(x)
        return self.avg_pooling(extracted_layers[-1]), extracted_layers
