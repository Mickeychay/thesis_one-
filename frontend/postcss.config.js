import autoprefixer from 'autoprefixer'
import tailwindcss from 'tailwindcss'

const preserveGeneratedNodeSource = {
  postcssPlugin: 'preserve-generated-node-source',
  Once(root) {
    const fallbackSource =
      root.source ?? root.nodes.find((node) => node.source)?.source

    if (!fallbackSource) return

    root.walk((node) => {
      node.source ??= fallbackSource
    })
  },
}

export default {
  plugins: [
    tailwindcss(),
    autoprefixer(),
    preserveGeneratedNodeSource,
  ],
}
