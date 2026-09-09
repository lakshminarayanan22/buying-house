import Image from "next/image";

/**
 * The Ecolink mark.
 *
 * The source file is a JPEG on warm paper rather than a transparent cutout, so it cannot
 * simply be dropped onto a graphite header — it would read as a pale rectangle stuck to
 * the hull. Setting the tile's own background to the artwork's paper colour turns that
 * limitation into the design: the edges disappear into the tile and the whole thing reads
 * as an enamel badge bolted to the console, which is what a real instrument panel does
 * with a maker's mark anyway.
 */
const PAPER = "#f0e7de"; // sampled from the artwork's own background

export function BrandMark({ size = 26 }: { size?: number }) {
  return (
    <span
      className="grid shrink-0 place-items-center overflow-hidden rounded-md"
      style={{
        width: size,
        height: size,
        background: PAPER,
        boxShadow: "0 0 0 1px var(--border-strong), 0 1px 6px -2px rgba(0,0,0,.5)",
      }}
    >
      <Image
        src="/brand/ecolink-mark.jpg"
        // Decorative: the wordmark beside it already carries the name, so announcing
        // "Ecolink" twice would only add noise for a screen reader.
        alt=""
        width={size}
        height={size}
        className="h-full w-full object-cover"
        priority
      />
    </span>
  );
}
