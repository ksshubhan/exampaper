import type { SVGProps } from 'react'

// Small, dependency-free stroke icons (lucide-style). Size via className.
function Svg(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    />
  )
}

export function HomeIcon(p: SVGProps<SVGSVGElement>) {
  return (
    <Svg {...p}>
      <path d="M3 11l9-8 9 8" />
      <path d="M5 10v10h14V10" />
    </Svg>
  )
}

export function PapersIcon(p: SVGProps<SVGSVGElement>) {
  return (
    <Svg {...p}>
      <rect x="5" y="3" width="14" height="18" rx="2" />
      <path d="M9 8h6M9 12h6M9 16h4" />
    </Svg>
  )
}

export function WorksheetIcon(p: SVGProps<SVGSVGElement>) {
  return (
    <Svg {...p}>
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
    </Svg>
  )
}

export function PricingIcon(p: SVGProps<SVGSVGElement>) {
  return (
    <Svg {...p}>
      <path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0l-7-7V4h9.6l7.4 7.4a2 2 0 0 1 0 2.8Z" />
      <circle cx="7.5" cy="7.5" r="1.1" />
    </Svg>
  )
}

export function AboutIcon(p: SVGProps<SVGSVGElement>) {
  return (
    <Svg {...p}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5" />
      <path d="M12 7.5h.01" />
    </Svg>
  )
}

export function SunIcon(p: SVGProps<SVGSVGElement>) {
  return (
    <Svg {...p}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </Svg>
  )
}

export function MoonIcon(p: SVGProps<SVGSVGElement>) {
  return (
    <Svg {...p}>
      <path d="M21 12.8A8.5 8.5 0 1 1 11.2 3a6.5 6.5 0 0 0 9.8 9.8Z" />
    </Svg>
  )
}

export function BracketsIcon(p: SVGProps<SVGSVGElement>) {
  return (
    <Svg {...p}>
      <path d="M8 6 3 12l5 6" />
      <path d="M16 6l5 6-5 6" />
    </Svg>
  )
}

export function SparkleIcon(p: SVGProps<SVGSVGElement>) {
  return (
    <Svg {...p}>
      <path d="M12 3l1.8 4.7L18.5 9l-4.7 1.8L12 15.5l-1.8-4.7L5.5 9l4.7-1.3Z" />
    </Svg>
  )
}

export function CheckIcon(p: SVGProps<SVGSVGElement>) {
  return (
    <Svg {...p}>
      <path d="M20 6 9 17l-5-5" />
    </Svg>
  )
}

export function SearchIcon(p: SVGProps<SVGSVGElement>) {
  return (
    <Svg {...p}>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.6-3.6" />
    </Svg>
  )
}

export function ChevronDownIcon(p: SVGProps<SVGSVGElement>) {
  return (
    <Svg {...p}>
      <path d="m6 9 6 6 6-6" />
    </Svg>
  )
}

export function ChevronRightIcon(p: SVGProps<SVGSVGElement>) {
  return (
    <Svg {...p}>
      <path d="m9 6 6 6-6 6" />
    </Svg>
  )
}
