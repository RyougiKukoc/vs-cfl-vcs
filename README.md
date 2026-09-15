# vs-cfl

Chroma-from-Luma for VapourSynth — 亮度引导的色度重建类算法集

## 函数签名

### kACfL

```python
cfl.KACFL(clip, pb=0.8, ep=2.0, cox=None, coy=None)
```

| 参数 | 类型 | 默认值 | 范围 | 说明 |
|------|------|--------|------|------|
| `pb` | float | `0.8` | `[0.0, 1.0]` | 预测混合权重。越大越依赖线性预测，越小越依赖空间滤波 |
| `ep` | float | `2.0` | `[0.0, 10.0]` | 边缘保护。越大则空间滤波对亮度差异越敏感，边缘越锐利 |
| `cox` | float | `None` | x | 亮度 X 偏移（像素）。 `None` 时从帧属性 `_ChromaLocation` 自动检测 |
| `coy` | float | `None` | x | 亮度 Y 偏移（像素）。 `None` 时从帧属性 `_ChromaLocation` 自动检测 |

自动检测模式从帧属性 `_ChromaLocation` 推导偏移。基准位置等价于亮度块中心，即 CENTER 色度位置，偏移表示从该中心到实际色度采样点的位移（单位：亮度像素）：

| ChromaLoc | cox | coy (420) | coy (422) |
|------|------|--------|------|
| LEFT | -0.5 | 0 | 0 |
| CENTER | 0 | 0 | 0 |
| TOP_LEFT | -0.5 | -0.5 | 0 |
| TOP | 0 | -0.5 | 0 |
| BOTTOM_LEFT | -0.5 | 0.5 | 0 |
| BOTTOM | 0 | 0.5 | 0 |

- 支持格式  
  输入： YUV420P8 YUV422P8 YUV420P9 YUV422P9 YUV420P10 YUV422P10 YUV420P12 YUV422P12 YUV420P14 YUV422P14 YUV420P16 YUV422P16  
  输出： YUV444P8/YUV444P9/YUV444P10/YUV444P12/YUV444P14/YUV444P16 （位深与输入一致）

## 构建

msvc, meson, ninja

```bash
meson setup build
meson compile -C build
```

> MSVC 需在 VS Developer Command Prompt 或执行 `vcvars64.bat` 后运行。

## Windows 安装（pip / Git）

在 Windows x86_64 上，安装当前仓库版本时可直接使用：

```powershell
pip install "vs-cfl @ git+https://github.com/RyougiKukoc/vs-cfl-vcs.git"
```

默认会下载与 `pyproject.toml` 版本对应的 GitHub Release 资产
`vs-cfl-msys2-ucrt64.zip`，并将 `vs_cfl.dll`、`manifest.vs` 与所需的
MSYS2 runtime DLL 安装到 `vapoursynth/plugins/vs_cfl/`。VapourSynth R77+
会通过 manifest 自动加载该插件，函数仍为 `core.cfl.KACFL`。

如果该版本还没有发布 Release 资产，安装钩子会回退到本地的
MSYS2/UCRT64 + Meson 构建。可设置 `VS_CFL_FORCE_BUILD=1` 强制走本地构建；
`VS_CFL_PREBUILT_URL` 可指定本地或远程 release zip，方便离线和 CI 测试。

## Release-backed pip install

The package name is `vs-cfl`. Version `1.0.2` uses Release tag `v1.0.2`.
On Linux x86_64, the documented installation downloads
`vs-cfl-linux-x86_64.zip` first and installs its `vs_cfl/` payload under
`vapoursynth/plugins/`:

```bash
pip install "vs-cfl @ git+https://github.com/RyougiKukoc/vs-cfl-vcs.git"
```

The Linux payload contains `manifest.vs` and `vs_cfl.so`. Linux payloads and
Linux source builds deliberately use the serial CPU implementation because the
optional OpenMP path is not stable across the conservative runtime baseline.
The published wheel is tagged `manylinux_2_27_x86_64`, matching the VapourSynth
R79 Linux runtime baseline. Windows x86_64 keeps using
`vs-cfl-msys2-ucrt64.zip` and its existing DLL payload.

Set `VS_CFL_FORCE_BUILD=1` to bypass a Release payload and build locally with
Meson. Native Linux and macOS builds require a compatible VapourSynth wheel in
the build environment; the build hook prepends that wheel's
`vapoursynth/pkgconfig` directory to any existing `PKG_CONFIG_PATH`. macOS has
no published payload and therefore always uses the native build path.

## 许可

MIT
