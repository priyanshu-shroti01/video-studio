/**
 * Remotion render settings tuned for Apple Silicon (M1 Pro: 8 performance + 2 efficiency cores).
 * Applies to `npx remotion render` and `npx remotion studio`.
 *
 * Every value can be overridden on the CLI (e.g. `--concurrency=4`) or via the env vars below.
 */
import {Config} from '@remotion/cli/config';

Config.setEntryPoint('src/index.ts');
Config.setOverwriteOutput(true);

// ---- Encoding: VideoToolbox (Apple media engine) ---------------------------------------
// 'if-possible' uses h264_videotoolbox on macOS and silently falls back to libx264 elsewhere.
// Hardware encoders ignore --crf, so quality is set by bitrate instead.
// 16 Mbps is comfortably above YouTube's recommendation for 1080p30 uploads.
Config.setCodec('h264');
Config.setHardwareAcceleration(
  (process.env.REMOTION_HW as 'disable' | 'if-possible' | 'required') ?? 'if-possible',
);
Config.setVideoBitrate(process.env.REMOTION_BITRATE ?? '16M');
Config.setPixelFormat('yuv420p'); // maximum player compatibility (YouTube / Instagram / WhatsApp)
Config.setAudioCodec('aac');
Config.setAudioBitrate('256k');

// ---- Frame capture: Chromium --------------------------------------------------------------
// 'angle' routes Chromium's GPU work through ANGLE -> Metal on macOS, so CSS filters,
// gradients, blur and WebGL are GPU-rendered instead of software-rasterised (swangle/swiftshader).
Config.setChromiumOpenGlRenderer('angle');
// JPEG frames are much faster to pipe to the encoder than PNG; switch to 'png' only
// if a composition needs transparency.
Config.setVideoImageFormat('jpeg');
Config.setJpegQuality(92);

// ---- Parallelism --------------------------------------------------------------------------
// 6 parallel Chromium tabs keeps the 8 P-cores busy while leaving headroom for the
// encoder and 16 GB of RAM. Lower via REMOTION_CONCURRENCY if the machine is busy.
Config.setConcurrency(Number(process.env.REMOTION_CONCURRENCY ?? 6));
