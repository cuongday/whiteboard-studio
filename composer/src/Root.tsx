import { Composition } from "remotion";
import { FinalVideo, VideoProps } from "./FinalVideo";

const defaults: VideoProps = { fps: 30, width: 1920, height: 1080, captions: true, music: null, scenes: [] };

export const RemotionRoot = () => (
  <Composition
    id="FinalVideo"
    component={FinalVideo}
    defaultProps={defaults}
    fps={30}
    width={1920}
    height={1080}
    durationInFrames={30}
    calculateMetadata={({ props }) => ({
      fps: props.fps, width: props.width, height: props.height,
      durationInFrames: Math.max(1, props.scenes.reduce((a, s) => a + s.durationInFrames, 0)),
    })}
  />
);
