/*
 *  kACfL
 *  Original GLSL shader by hooke007
 */

#include <algorithm>
#include <cfloat>
#include <cmath>
#include <cstdint>
#include <memory>
#include <vector>

#include "VapourSynth4.h"
#include "VSHelper4.h"
#include "VSConstants4.h"
#include "kACfL.h"

static constexpr float COX_COY_AUTO = -FLT_MAX;

struct KACfLData {
    VSNode *node;
    VSVideoInfo vi;   // output format (YUV444, same bit depth)
    float pb;         // prediction blend weight   [0, 1]   default 0.8
    float ep;         // edge protection parameter [0, 10]  default 2.0
    float cox;        // luma X offset (pixels) or COX_COY_AUTO
    float coy;        // luma Y offset (pixels) or COX_COY_AUTO
    int   subW;       // log2 horizontal subsampling of input (1)
    int   subH;       // log2 vertical   subsampling of input (0 or 1)
};

// ---------------------------------------------------------------------------
// Chroma location -> luma-pixel offset
// ---------------------------------------------------------------------------

static void chromaLocationToOffset(int chromaLoc, int subW, int subH,
                                   float &outCox, float &outCoy) noexcept
{
    // Compute luma-pixel offset from the CENTER of the luma block to the
    // actual chroma sample position.
    //
    // Base position (cx+0.5)/chromaW = (2*cx+1)/lumaW sits at the CENTER
    // of the 2-pixel luma block — this naturally matches CENTER chroma loc.
    //
    // Horizontal (subW == 1, 2x horizontal subsampling):
    //   CENTER / TOP / BOTTOM          ->  0     (already at center)
    //   LEFT / TOP_LEFT / BOTTOM_LEFT  -> -0.5   (co-sited with left luma)
    //
    // Vertical (subH == 1, 2x vertical subsampling, 420):
    //   LEFT / CENTER                  ->  0     (vertically centered)
    //   TOP_LEFT / TOP                 -> -0.5   (co-sited with top row)
    //   BOTTOM_LEFT / BOTTOM           -> +0.5   (co-sited with bottom row)

    float cx = 0.0f, cy = 0.0f;

    if (subW == 1) {
        switch (chromaLoc) {
        case VSC_CHROMA_LEFT:
        case VSC_CHROMA_TOP_LEFT:
        case VSC_CHROMA_BOTTOM_LEFT:
            cx = -0.5f;
            break;
        default: // CENTER, TOP, BOTTOM
            cx = 0.0f;
            break;
        }
    }

    if (subH == 1) {
        switch (chromaLoc) {
        case VSC_CHROMA_TOP_LEFT:
        case VSC_CHROMA_TOP:
            cy = -0.5f;
            break;
        case VSC_CHROMA_BOTTOM_LEFT:
        case VSC_CHROMA_BOTTOM:
            cy = 0.5f;
            break;
        default: // LEFT, CENTER
            cy = 0.0f;
            break;
        }
    }

    outCox = cx;
    outCoy = cy;
}

// ---------------------------------------------------------------------------
// Core algo
// ---------------------------------------------------------------------------

struct ChromaSample {
    float l, u, v;
};

template<typename T>
static void processFrame(
    const uint8_t * VS_RESTRICT srcYPtr,  ptrdiff_t srcYStride,
    const uint8_t * VS_RESTRICT srcUPtr,  ptrdiff_t srcUStride,
    const uint8_t * VS_RESTRICT srcVPtr,  ptrdiff_t srcVStride,
    uint8_t       * VS_RESTRICT dstUPtr,  ptrdiff_t dstUStride,
    uint8_t       * VS_RESTRICT dstVPtr,  ptrdiff_t dstVStride,
    int lumaW, int lumaH,
    int chromaW, int chromaH,
    int bitsPerSample,
    float pb, float ep, float cox, float coy) noexcept
{
    const int   peak     = (1 << bitsPerSample) - 1;
    const float peakf    = static_cast<float>(peak);
    const float inv_peak = 1.0f / peakf;
    const float sub_x    = static_cast<float>(lumaW) / chromaW;
    const float sub_y    = static_cast<float>(lumaH) / chromaH;

    // -----------------------------------------------------------------------
    // Pass 1 - Interleaved chroma-resolution buffer (luma_lr + cb + cr)
    // -----------------------------------------------------------------------

    const size_t chromaSize = static_cast<size_t>(chromaW) * chromaH;
    std::vector<ChromaSample> buf(chromaSize);

    for (int cy = 0; cy < chromaH; ++cy) {
        const T *rowU = reinterpret_cast<const T *>(srcUPtr + cy * srcUStride);
        const T *rowV = reinterpret_cast<const T *>(srcVPtr + cy * srcVStride);
        ChromaSample *bufRow = buf.data() + static_cast<size_t>(cy) * chromaW;

        for (int cx = 0; cx < chromaW; ++cx) {
            float pos_x = (cx + 0.5f) / chromaW + cox / lumaW;
            float pos_y = (cy + 0.5f) / chromaH + coy / lumaH;

            float luma_avg;

            if (sub_x > 1.5f && sub_y > 1.5f) {
                // 4:2:0 — 2x2 box average
                int lx = static_cast<int>(std::floor(pos_x * lumaW - 0.5f));
                int ly = static_cast<int>(std::floor(pos_y * lumaH - 0.5f));
                int lx0 = std::clamp(lx,     0, lumaW - 1);
                int lx1 = std::clamp(lx + 1, 0, lumaW - 1);
                int ly0 = std::clamp(ly,     0, lumaH - 1);
                int ly1 = std::clamp(ly + 1, 0, lumaH - 1);
                const T *row0 = reinterpret_cast<const T *>(srcYPtr + ly0 * srcYStride);
                const T *row1 = reinterpret_cast<const T *>(srcYPtr + ly1 * srcYStride);
                luma_avg = (row0[lx0] + row0[lx1] + row1[lx0] + row1[lx1]) * 0.25f * inv_peak;
            } else if (sub_x > 1.5f) {
                // 4:2:2 — 1x2 horizontal average
                int lx = static_cast<int>(std::floor(pos_x * lumaW - 0.5f));
                int ly = static_cast<int>(std::floor(pos_y * lumaH));
                int lx0 = std::clamp(lx,     0, lumaW - 1);
                int lx1 = std::clamp(lx + 1, 0, lumaW - 1);
                ly       = std::clamp(ly,     0, lumaH - 1);
                const T *row = reinterpret_cast<const T *>(srcYPtr + ly * srcYStride);
                luma_avg = (row[lx0] + row[lx1]) * 0.5f * inv_peak;
            } else {
                int lx = static_cast<int>(std::floor(pos_x * lumaW));
                int ly = static_cast<int>(std::floor(pos_y * lumaH));
                lx = std::clamp(lx, 0, lumaW - 1);
                ly = std::clamp(ly, 0, lumaH - 1);
                const T *row = reinterpret_cast<const T *>(srcYPtr + ly * srcYStride);
                luma_avg = row[lx] * inv_peak;
            }

            bufRow[cx] = { luma_avg, rowU[cx] * inv_peak, rowV[cx] * inv_peak };
        }
    }

    // -----------------------------------------------------------------------
    // Precompute spatial weight LUT
    // -----------------------------------------------------------------------

    const bool is_420 = (sub_x > 1.5f && sub_y > 1.5f);
    const int  num_fy = is_420 ? 2 : 1;

    float sw_lut[2][2][16];
    for (int fxi = 0; fxi < 2; ++fxi) {
        float cpx = (fxi + 0.5f) / sub_x;
        float ppx = cpx - 0.5f;
        float fx  = ppx - std::floor(ppx);
        for (int fyi = 0; fyi < num_fy; ++fyi) {
            float cpy = (fyi + 0.5f) / sub_y;
            float ppy = cpy - 0.5f;
            float fy  = ppy - std::floor(ppy);
            for (int j = 0; j < 4; ++j) {
                for (int i = 0; i < 4; ++i) {
                    float di = static_cast<float>(i - 1) - fx;
                    float dj = static_cast<float>(j - 1) - fy;
                    float dist = std::sqrt(di * di + dj * dj);
                    float sw = std::max(1.0f - dist * 0.5f, 0.0f);
                    sw *= sw;
                    sw_lut[fxi][fyi][j * 4 + i] = sw;
                }
            }
        }
    }

    // -----------------------------------------------------------------------
    // Pass 2 — CfL Prediction
    // -----------------------------------------------------------------------

    const float range_sigma = (ep > 0.0f) ? (0.1f / ep) : 1e6f;
    const float neg_half_inv_rsq = -0.5f / (range_sigma * range_sigma);

#ifdef _OPENMP
    #pragma omp parallel for schedule(dynamic, 16)
#endif
    for (int oy = 0; oy < lumaH; ++oy) {

        const T *srcRowY = reinterpret_cast<const T *>(srcYPtr + oy * srcYStride);
        T       *dstRowU = reinterpret_cast<T *>(dstUPtr + oy * dstUStride);
        T       *dstRowV = reinterpret_cast<T *>(dstVPtr + oy * dstVStride);

        const int fyi = is_420 ? (oy & 1) : 0;

        // Hoist row-constant computations
        float cpos_y = (oy + 0.5f) / sub_y;
        float pp_y   = cpos_y - 0.5f;
        int   fp_y   = static_cast<int>(std::floor(pp_y));

        int sp_y[4];
        for (int j = 0; j < 4; ++j)
            sp_y[j] = std::clamp(fp_y + j - 1, 0, chromaH - 1);

        const ChromaSample *rows[4];
        for (int j = 0; j < 4; ++j)
            rows[j] = buf.data() + static_cast<size_t>(sp_y[j]) * chromaW;

        for (int ox = 0; ox < lumaW; ++ox) {
            float luma_hr = srcRowY[ox] * inv_peak;

            float cpos_x = (ox + 0.5f) / sub_x;
            float pp_x   = cpos_x - 0.5f;
            int   fp_x   = static_cast<int>(std::floor(pp_x));

            const float *sw = sw_lut[ox & 1][fyi];

            // Gather 4x4 from interleaved buffer
            float luma_samples[16];
            float cb_samples[16];
            float cr_samples[16];

            for (int j = 0; j < 4; ++j) {
                for (int i = 0; i < 4; ++i) {
                    int sp_x = std::clamp(fp_x + i - 1, 0, chromaW - 1);
                    int idx   = j * 4 + i;
                    const ChromaSample &s = rows[j][sp_x];
                    luma_samples[idx] = s.l;
                    cb_samples[idx]   = s.u;
                    cr_samples[idx]   = s.v;
                }
            }

            // Loop 1: means
            float luma_sum = 0.0f, cb_sum = 0.0f, cr_sum = 0.0f;
            for (int i = 0; i < 16; ++i) {
                luma_sum += luma_samples[i];
                cb_sum   += cb_samples[i];
                cr_sum   += cr_samples[i];
            }
            float luma_mean = luma_sum * 0.0625f;
            float cb_mean   = cb_sum   * 0.0625f;
            float cr_mean   = cr_sum   * 0.0625f;

            // Loop 2: covariance + all variances (merged)
            float luma_var = 0.0f;
            float cov_cb = 0.0f, cov_cr = 0.0f;
            float var_cb = 0.0f, var_cr = 0.0f;
            for (int i = 0; i < 16; ++i) {
                float ld   = luma_samples[i] - luma_mean;
                float cd_u = cb_samples[i] - cb_mean;
                float cd_v = cr_samples[i] - cr_mean;
                luma_var += ld * ld;
                cov_cb   += ld * cd_u;
                cov_cr   += ld * cd_v;
                var_cb   += cd_u * cd_u;
                var_cr   += cd_v * cd_v;
            }

            // Linear regression
            float inv_lv   = 1.0f / std::max(luma_var, 1e-6f);
            float alpha_cb = std::clamp(cov_cb * inv_lv, -2.0f, 2.0f);
            float alpha_cr = std::clamp(cov_cr * inv_lv, -2.0f, 2.0f);

            float luma_diff = luma_hr - luma_mean;
            float pred_cb = alpha_cb * luma_diff + cb_mean;
            float pred_cr = alpha_cr * luma_diff + cr_mean;

            // Correlation
            float corr_cb = std::clamp(
                std::abs(cov_cb) / std::max(std::sqrt(luma_var * var_cb), 1e-6f),
                0.0f, 1.0f);
            float corr_cr = std::clamp(
                std::abs(cov_cr) / std::max(std::sqrt(luma_var * var_cr), 1e-6f),
                0.0f, 1.0f);

            // Bilateral spatial filter (precomputed spatial weights)
            float spatial_cb = 0.0f, spatial_cr = 0.0f;
            float weight_sum = 0.0f;
            float luma_center = luma_samples[5];

            for (int k = 0; k < 16; ++k) {
                float ld = luma_samples[k] - luma_center;
                float rw = std::exp(ld * ld * neg_half_inv_rsq);
                float w  = sw[k] * rw;
                spatial_cb += w * cb_samples[k];
                spatial_cr += w * cr_samples[k];
                weight_sum += w;
            }
            spatial_cb /= std::max(weight_sum, 1e-6f);
            spatial_cr /= std::max(weight_sum, 1e-6f);

            // Blend
            float blend_cb = corr_cb * corr_cb * pb;
            float blend_cr = corr_cr * corr_cr * pb;

            float out_cb = std::clamp(spatial_cb + blend_cb * (pred_cb - spatial_cb), 0.0f, 1.0f);
            float out_cr = std::clamp(spatial_cr + blend_cr * (pred_cr - spatial_cr), 0.0f, 1.0f);

            dstRowU[ox] = static_cast<T>(std::clamp(
                static_cast<int>(out_cb * peakf + 0.5f), 0, peak));
            dstRowV[ox] = static_cast<T>(std::clamp(
                static_cast<int>(out_cr * peakf + 0.5f), 0, peak));
        }
    }
}

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------

static const VSFrame * VS_CC kacflGetFrame(
    int n, int activationReason,
    void *instanceData, void **frameData,
    VSFrameContext *frameCtx, VSCore *core, const VSAPI *vsapi) noexcept
{
    auto *d = static_cast<KACfLData *>(instanceData);

    if (activationReason == arInitial) {
        vsapi->requestFrameFilter(n, d->node, frameCtx);

    } else if (activationReason == arAllFramesReady) {
        const VSFrame *src = vsapi->getFrameFilter(n, d->node, frameCtx);
        const VSVideoFormat *srcFmt = vsapi->getVideoFrameFormat(src);

        int lumaW   = vsapi->getFrameWidth(src,  0);
        int lumaH   = vsapi->getFrameHeight(src, 0);
        int chromaW = vsapi->getFrameWidth(src,  1);
        int chromaH = vsapi->getFrameHeight(src, 1);

        // Resolve chroma offsets
        float cox = d->cox;
        float coy = d->coy;

        if (cox == COX_COY_AUTO || coy == COX_COY_AUTO) {
            const VSMap *props = vsapi->getFramePropertiesRO(src);
            int err;
            int chromaLoc = vsapi->mapGetIntSaturated(props, "_ChromaLocation", 0, &err);
            if (err) chromaLoc = VSC_CHROMA_LEFT;

            float auto_cox, auto_coy;
            chromaLocationToOffset(chromaLoc, d->subW, d->subH, auto_cox, auto_coy);

            if (cox == COX_COY_AUTO) cox = auto_cox;
            if (coy == COX_COY_AUTO) coy = auto_coy;
        }

        const VSFrame *planeSrc[3] = { src, nullptr, nullptr };
        int            planeIdx[3] = { 0, 0, 0 };
        VSFrame *dst = vsapi->newVideoFrame2(&d->vi.format,
                                             lumaW, lumaH,
                                             planeSrc, planeIdx,
                                             src, core);

        const uint8_t *srcY = vsapi->getReadPtr(src, 0);
        const uint8_t *srcU = vsapi->getReadPtr(src, 1);
        const uint8_t *srcV = vsapi->getReadPtr(src, 2);
        ptrdiff_t srcYStride = vsapi->getStride(src, 0);
        ptrdiff_t srcUStride = vsapi->getStride(src, 1);
        ptrdiff_t srcVStride = vsapi->getStride(src, 2);

        uint8_t *dstU = vsapi->getWritePtr(dst, 1);
        uint8_t *dstV = vsapi->getWritePtr(dst, 2);
        ptrdiff_t dstUStride = vsapi->getStride(dst, 1);
        ptrdiff_t dstVStride = vsapi->getStride(dst, 2);

        if (srcFmt->bytesPerSample == 1) {
            processFrame<uint8_t>(
                srcY, srcYStride, srcU, srcUStride, srcV, srcVStride,
                dstU, dstUStride, dstV, dstVStride,
                lumaW, lumaH, chromaW, chromaH,
                srcFmt->bitsPerSample,
                d->pb, d->ep, cox, coy);
        } else {
            processFrame<uint16_t>(
                srcY, srcYStride, srcU, srcUStride, srcV, srcVStride,
                dstU, dstUStride, dstV, dstVStride,
                lumaW, lumaH, chromaW, chromaH,
                srcFmt->bitsPerSample,
                d->pb, d->ep, cox, coy);
        }

        vsapi->freeFrame(src);
        return dst;
    }

    return nullptr;
}

static void VS_CC kacflFree(void *instanceData, VSCore *core,
                            const VSAPI *vsapi) noexcept
{
    auto *d = static_cast<KACfLData *>(instanceData);
    vsapi->freeNode(d->node);
    delete d;
}

static void VS_CC kacflCreate(const VSMap *in, VSMap *out, void *userData,
                              VSCore *core, const VSAPI *vsapi) noexcept
{
    VSNode *node = vsapi->mapGetNode(in, "clip", 0, nullptr);
    const VSVideoInfo *vi = vsapi->getVideoInfo(node);

    if (!vsh::isConstantVideoFormat(vi)) {
        vsapi->mapSetError(out, "KACFL: input must have constant format");
        vsapi->freeNode(node);
        return;
    }

    if (vi->format.colorFamily != cfYUV) {
        vsapi->mapSetError(out, "KACFL: input must be YUV color family");
        vsapi->freeNode(node);
        return;
    }

    if (vi->format.sampleType != stInteger) {
        vsapi->mapSetError(out, "KACFL: input must be integer sample type");
        vsapi->freeNode(node);
        return;
    }

    if (vi->format.subSamplingW != 1 ||
        (vi->format.subSamplingH != 0 && vi->format.subSamplingH != 1)) {
        vsapi->mapSetError(out, "KACFL: input must be YUV420 or YUV422 subsampling");
        vsapi->freeNode(node);
        return;
    }

    int bps = vi->format.bitsPerSample;
    if (bps != 8 && bps != 9 && bps != 10 && bps != 12 && bps != 14 && bps != 16) {
        vsapi->mapSetError(out, "KACFL: unsupported bit depth (allowed: 8/9/10/12/14/16)");
        vsapi->freeNode(node);
        return;
    }

    int err;
    double pb  = vsapi->mapGetFloat(in, "pb",  0, &err);  if (err) pb  = 0.8;
    double ep  = vsapi->mapGetFloat(in, "ep",  0, &err);  if (err) ep  = 2.0;

    double cox_d = vsapi->mapGetFloat(in, "cox", 0, &err);
    float  cox   = err ? COX_COY_AUTO : static_cast<float>(cox_d);

    double coy_d = vsapi->mapGetFloat(in, "coy", 0, &err);
    float  coy   = err ? COX_COY_AUTO : static_cast<float>(coy_d);

    auto data   = std::make_unique<KACfLData>();
    data->node  = node;
    data->vi    = *vi;
    data->pb    = static_cast<float>(pb);
    data->ep    = static_cast<float>(ep);
    data->cox   = cox;
    data->coy   = coy;
    data->subW  = vi->format.subSamplingW;
    data->subH  = vi->format.subSamplingH;

    if (!vsapi->queryVideoFormat(&data->vi.format,
                                 cfYUV, stInteger, bps, 0, 0, core)) {
        vsapi->mapSetError(out, "KACFL: failed to query output format (YUV444)");
        vsapi->freeNode(node);
        return;
    }

    VSFilterDependency deps[] = { { node, rpStrictSpatial } };
    auto *raw = data.release();
    vsapi->createVideoFilter(out, "KACFL", &raw->vi,
                             kacflGetFrame, kacflFree,
                             fmParallel, deps, 1, raw, core);
}

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------

void kacflRegister(VSPlugin *plugin, const VSPLUGINAPI *vspapi)
{
    vspapi->registerFunction(
        "KACFL",
        "clip:vnode;"
        "pb:float:opt;"
        "ep:float:opt;"
        "cox:float:opt;"
        "coy:float:opt;",
        "clip:vnode;",
        kacflCreate,
        nullptr,
        plugin);
}
