import { AbsoluteFill, Audio, OffthreadVideo, Series, staticFile, useVideoConfig } from "remotion";
import { Captions, Word } from "./Captions";

export type SceneProps = { clip: string; audio: string; durationInFrames: number; words: Word[] };
export type VideoProps = { fps: number; width: number; height: number; captions: boolean; music: string | null; scenes: SceneProps[] };

const Music: React.FC<{ src: string; scenes: SceneProps[] }> = ({ src, scenes }) => {
  const { fps } = useVideoConfig();
  // speech intervals in absolute frames, used for ducking
  const spans: [number, number][] = [];
  let offset = 0;
  for (const s of scenes) {
    if (s.words.length) spans.push([offset + (s.words[0].start_ms / 1000) * fps, offset + (s.words[s.words.length - 1].end_ms / 1000) * fps]);
    offset += s.durationInFrames;
  }
  return (
    <Audio src={staticFile(src)} loop volume={(f) => {
      const speaking = spans.some(([a, b]) => f >= a - 8 && f <= b + 8);
      return speaking ? 0.08 : 0.3;
    }} />
  );
};

export const FinalVideo: React.FC<VideoProps> = ({ scenes, captions, music }) => (
  <AbsoluteFill style={{ backgroundColor: "#F5EBD7" }}>
    <Series>
      {scenes.map((s, i) => (
        <Series.Sequence key={i} durationInFrames={s.durationInFrames}>
          <OffthreadVideo src={staticFile(s.clip)} muted />
          <Audio src={staticFile(s.audio)} />
          {captions && <Captions words={s.words} />}
        </Series.Sequence>
      ))}
    </Series>
    {music && <Music src={music} scenes={scenes} />}
  </AbsoluteFill>
);
