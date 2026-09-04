"""Shared offset pledge progress palette (low → high share)."""

OFFSET_PROGRESS_PALETTE = [
    "#ff5117",  # tiger-flame
    "#ff7547",  # coral-glow
    "#ff9c7a",  # tangerine-dream
    "#ffaf94",  # powder-blush
    "#ffc2ad",  # powder-blush-2
    "#dccf9d",  # vanilla-custard
    "#b7c384",  # muted-olive
    "#91b66a",  # muted-olive-2
    "#76ac3c",  # bright-fern
    "#5aa20d",  # bright-fern-2
]

OFFSET_CHOROPLETH_META = {
    "enabled": True,
    "colour_palette": OFFSET_PROGRESS_PALETTE,
    "colour_low": OFFSET_PROGRESS_PALETTE[0],
    "colour_high": OFFSET_PROGRESS_PALETTE[-1],
}
