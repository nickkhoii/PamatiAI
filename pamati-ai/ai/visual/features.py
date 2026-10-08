from statistics import fmean, pstdev

from ai.visual.interface import ObservableFeatures, VisualMetadata


class NoExpressionExtractor:
    metadata = VisualMetadata(
        "no-expression-extractor", "1",
        limitations=("No facial action-unit or behavioral-expression extractor is deployed.",),
    )

    def extract(self, frames):
        return ObservableFeatures()


def frame_quality(frames):
    """Whole-frame technical measurements only; do not detect people or facial attributes."""
    luminances, contrasts, clipping = [], [], []
    for frame in frames:
        # Rec. 601-style luma approximation, normalized to [0, 1]; no calibrated photometry.
        values = [(.299 * r + .587 * g + .114 * b) / 255
                  for r, g, b in zip(frame.rgb[0::3], frame.rgb[1::3], frame.rgb[2::3], strict=True)]
        luminances.append(fmean(values))
        contrasts.append(pstdev(values))
        clipping.append(sum(v <= .01 or v >= .99 for v in values) / len(values))
    return {
        "mean_frame_luminance": fmean(luminances),
        "mean_frame_luminance_std": fmean(contrasts),
        "mean_extreme_luminance_fraction": fmean(clipping),
        "method": "whole_frame_pixel_summary_v1",
        "face_presence": "not_established", "expression_quality": "not_established",
    }
