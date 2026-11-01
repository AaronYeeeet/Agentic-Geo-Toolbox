import { describe, expect, test } from 'vitest'
import de from './de.json'
import en from './en.json'

type Tree = { [key: string]: string | Tree }

function flatten(tree: Tree, prefix = ''): Record<string, string> {
  return Object.entries(tree).reduce<Record<string, string>>((acc, [key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key
    if (typeof value === 'string') acc[path] = value
    else Object.assign(acc, flatten(value, path))
    return acc
  }, {})
}

const enKeys = flatten(en as Tree)
const deKeys = flatten(de as Tree)
const placeholders = (text: string) => [...text.matchAll(/{{\s*(\w+)\s*}}/g)].map((m) => m[1]).sort()

describe('translations', () => {
  test('English and German have the same keys', () => {
    expect(Object.keys(deKeys).sort()).toEqual(Object.keys(enKeys).sort())
  })

  test('no translation is empty', () => {
    for (const [key, value] of Object.entries({ ...enKeys, ...deKeys })) {
      expect(value.trim(), key).not.toBe('')
    }
  })

  test('both languages use the same interpolation variables', () => {
    for (const key of Object.keys(enKeys)) {
      expect(placeholders(deKeys[key] ?? ''), key).toEqual(placeholders(enKeys[key]))
    }
  })
})
