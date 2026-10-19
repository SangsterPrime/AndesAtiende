import { useEffect, useRef, useState } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { MeshDistortMaterial } from '@react-three/drei'
import type { Mesh } from 'three'
import type { ChatPhase } from '../lib/chat'
import { StaticOrb } from './StaticOrb'

function Sphere({ phase }: { phase: ChatPhase }) {
  const mesh = useRef<Mesh>(null)
  const busy = phase === 'loading'
  const color = phase === 'error' || phase === 'offline' ? '#426380' : '#25cde6'
  useFrame(({ clock }, delta) => {
    if (!mesh.current) return
    mesh.current.rotation.y += Math.min(delta, 0.05) * (busy ? 0.4 : 0.12)
    mesh.current.rotation.z = Math.sin(clock.elapsedTime * 0.25) * 0.06
  })
  return (
    <group rotation={[0.25, 0, -0.2]}>
      <mesh ref={mesh}>
        <icosahedronGeometry args={[1.55, 5]} />
        <MeshDistortMaterial color={color} roughness={0.27} metalness={0.65} distort={busy ? 0.24 : 0.12} speed={busy ? 2.2 : 0.8} />
      </mesh>
      <mesh scale={1.015}>
        <icosahedronGeometry args={[1.55, 2]} />
        <meshBasicMaterial color="#6aeaff" wireframe transparent opacity={0.12} />
      </mesh>
    </group>
  )
}

export default function OrbScene({ phase, onFailure }: { phase: ChatPhase; onFailure: () => void }) {
  const [visible, setVisible] = useState(!document.hidden)
  useEffect(() => {
    const update = () => setVisible(!document.hidden)
    document.addEventListener('visibilitychange', update)
    return () => document.removeEventListener('visibilitychange', update)
  }, [])
  return (
    <Canvas
      camera={{ position: [0, 0, 5.6], fov: 45 }}
      dpr={[1, 1.5]}
      frameloop={visible ? 'always' : 'never'}
      gl={{ alpha: true, antialias: false, powerPreference: 'low-power' }}
      fallback={<StaticOrb />}
      onCreated={({ gl }) => {
        gl.domElement.addEventListener('webglcontextlost', (event) => {
          event.preventDefault()
          onFailure()
        }, { once: true })
      }}
    >
      <ambientLight intensity={1.2} />
      <pointLight position={[3, 4, 4]} intensity={35} color="#b6faff" />
      <pointLight position={[-3, -1, 2]} intensity={18} color="#2156ef" />
      <Sphere phase={phase} />
    </Canvas>
  )
}
