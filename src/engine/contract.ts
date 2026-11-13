import {CONTRACT_VERSION, Format, RenderProps, SUPPORTED_CONTRACT_VERSIONS} from './types';

export const DIMENSIONS: Record<Format, {width: number; height: number}> = {
  short: {width: 1080, height: 1920},
  landscape: {width: 1920, height: 1080},
};

/** v2-only behaviour (layout reserves, viewBox logo aspects, hook-tag ceiling, watermark) is gated on this. */
export const isV2 = (props: Pick<RenderProps, 'contractVersion'>) => props.contractVersion >= 2;

/** Throws a clear error when the orchestrator and the engine disagree on the contract. */
export const assertContract = (props: Pick<RenderProps, 'contractVersion' | 'format' | 'fps' | 'durationInFrames'>) => {
  if (!SUPPORTED_CONTRACT_VERSIONS.includes(props.contractVersion)) {
    throw new Error(
      `RenderProps contractVersion ${String(props.contractVersion)} is not supported by this engine (CONTRACT_VERSION ${CONTRACT_VERSION}, ` +
        `accepts ${SUPPORTED_CONTRACT_VERSIONS.join(' | ')}). Update pipeline/contract.py and src/engine/types.ts together.`,
    );
  }
  if (!(props.format in DIMENSIONS)) throw new Error(`Unknown format "${String(props.format)}" (expected short | landscape)`);
  if (!(props.fps > 0) || !(props.durationInFrames > 0)) throw new Error('fps and durationInFrames must be positive');
};
