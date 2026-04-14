import Image from "next/image";

type BrandMarkProps = {
  alt?: string;
  className?: string;
  priority?: boolean;
};

export function BrandMark({
  alt = "",
  className,
  priority = false,
}: BrandMarkProps) {
  return (
    <Image
      src="/logo-600.png"
      alt={alt}
      width={600}
      height={600}
      className={className}
      priority={priority}
    />
  );
}
