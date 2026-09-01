export function ArtifactId({ value }: { value: string }) {
  return <code className="artifact-id" title={value}>{value}</code>
}
