import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import os
import pandas as pd
import warnings
from matplotlib.collections import LineCollection
from matplotlib.path import Path
from matplotlib.widgets import Button, LassoSelector
from ruamel.yaml import YAML
from scipy.spatial import cKDTree as KDTree
from skimage import io


def read_config(configname):
    if not os.path.exists(configname):
        raise FileNotFoundError(
            f"Config {configname} is not found. Please make sure that the file exists."
        )
    with open(configname) as file:
        return YAML().load(file)


def write_config(configname, cfg):
    with open(configname, "w") as file:
        YAML().dump(cfg, file)


class SkeletonBuilder:
    def __init__(self, config_path):
        self.config_path = config_path
        self.cfg = read_config(config_path)
        # Find uncropped labeled data
        root = os.path.join(self.cfg["project_path"], "labeled-data")
        for dir_ in os.listdir(root):
            folder = os.path.join(root, dir_)
            if os.path.isdir(folder) and not any(
                folder.endswith(s) for s in ("cropped", "labeled")
            ):
                break
        self.df = pd.read_hdf(
            os.path.join(folder, f'CollectedData_{self.cfg["scorer"]}.h5')
        )
        row, col = self.pick_labeled_frame()
        if "individuals" in self.df.columns.names:
            self.df = self.df.xs(col, axis=1, level="individuals")
        self.bpts = self.df.columns.get_level_values("bodyparts").unique()
        self.xy = self.df.loc[row].values.reshape((-1, 2))
        self.tree = KDTree(self.xy)
        self.image = io.imread(os.path.join(self.cfg["project_path"], row))
        self.inds = set()
        self.segs = set()
        self.lines = LineCollection(
            self.segs, colors=mcolors.to_rgba(self.cfg["skeleton_color"])
        )
        self.lines.set_picker(True)
        self.show()

    def pick_labeled_frame(self):
        try:
            mask = self.df.groupby(level="individuals", axis=1).apply(self.all_visible)
            if "single" in mask:
                mask.drop("single", axis=1, inplace=True)
        except KeyError:
            mask = self.all_visible(self.df).to_frame()
        valid = mask[mask].stack().index.to_list()
        if not valid:
            raise ValueError("No fully labeled animal was found.")

        np.random.shuffle(valid)
        row, col = valid.pop()
        return row, col

    def show(self):
        self.fig = plt.figure()
        ax = self.fig.add_subplot(111)
        ax.axis("off")
        lo = np.min(self.xy, axis=0)
        hi = np.max(self.xy, axis=0)
        center = (hi + lo) / 2
        w, h = hi - lo
        ampl = 1.3
        w *= ampl
        h *= ampl
        ax.set_xlim(center[0] - w / 2, center[0] + w / 2)
        ax.set_ylim(center[1] - h / 2, center[1] + h / 2)
        ax.imshow(self.image)
        ax.scatter(*self.xy.T, s=self.cfg["dotsize"] ** 2)
        ax.add_collection(self.lines)
        ax.invert_yaxis()

        self.lasso = LassoSelector(ax, onselect=self.on_select)
        ax_clear = self.fig.add_axes([0.85, 0.55, 0.1, 0.1])
        ax_export = self.fig.add_axes([0.85, 0.45, 0.1, 0.1])
        self.clear_button = Button(ax_clear, "Clear")
        self.clear_button.on_clicked(self.clear)
        self.export_button = Button(ax_export, "Export")
        self.export_button.on_clicked(self.export)
        self.fig.canvas.mpl_connect("pick_event", self.on_pick)
        plt.show()

    def clear(self, *args):
        self.inds.clear()
        self.segs.clear()
        self.lines.set_segments(self.segs)

    def export(self, *args):
        inds_flat = set(ind for pair in self.inds for ind in pair)
        unconnected = [i for i in range(len(self.xy)) if i not in inds_flat]
        if len(unconnected):
            warnings.warn(
                f'Unconnected {", ".join(self.bpts[unconnected])}. '
                f"It is desirable that all bodyparts be connected for multi-animal projects."
            )
        self.cfg["skeleton"] = [tuple(self.bpts[list(pair)]) for pair in self.inds]
        write_config(self.config_path, self.cfg)

    def on_pick(self, event):
        if event.mouseevent.button == 3:
            removed = event.artist.get_segments().pop(event.ind[0])
            self.segs.remove(tuple(map(tuple, removed)))
            self.inds.remove(tuple(self.tree.query(removed)[1]))

    def on_select(self, verts):
        self.path = Path(verts)
        self.verts = verts
        inds = self.tree.query_ball_point(verts, 5)
        inds_unique = []
        for lst in inds:
            if len(lst) and lst[0] not in inds_unique:
                inds_unique.append(lst[0])
        for pair in zip(inds_unique, inds_unique[1:]):
            pair_sorted = tuple(sorted(pair))
            self.inds.add(pair_sorted)
            self.segs.add(tuple(map(tuple, self.xy[pair_sorted, :])))
        self.lines.set_segments(self.segs)
        self.fig.canvas.draw_idle()

    @staticmethod
    def all_visible(df):
        return ~df.isna().any(axis=1)
