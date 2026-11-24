import { Composition } from 'remotion';
import { Ps5Main } from './ps5/Main';
import { PS5_TOTAL } from './ps5/timeline';

export const Root: React.FC = () => {
  return (
    <Composition
      id="XYCtoPS5Promo"
      component={Ps5Main}
      durationInFrames={PS5_TOTAL}
      fps={30}
      width={1920}
      height={1080}
    />
  );
};
