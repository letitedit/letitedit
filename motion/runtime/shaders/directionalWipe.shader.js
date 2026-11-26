/*
MIT License

Copyright (c) 2017-present gl-transitions contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Note: Individual transitions in the transitions/ directory may have their own
license specified in their file header comments. When no license is specified,
the transition is covered by this MIT license.
*/
M.shader.define("directionalWipe", {"kind": "transition", "defaults": {"direction": [1.0, -1.0], "smoothness": 0.5}, "fragment": "uniform sampler2D tFrom; uniform sampler2D tTo; uniform float progress; uniform float ratio; varying vec2 vUv;\nvec4 getFromColor(vec2 uv) { return texture2D(tFrom, uv); }\nvec4 getToColor(vec2 uv) { return texture2D(tTo, uv); }\n// Author: gre\n// License: MIT\n// Description: A straight wipe in any direction, diagonal and soft-edged by default; a smoothness of 0 gives a hard edge\n// Tags: wipe, directional\n\n// @param Direction of the wipe\nuniform vec2 direction; // = vec2(1.0, -1.0)\n// @param Softness of the edge\nuniform float smoothness; // = 0.5\n \nconst vec2 center = vec2(0.5, 0.5);\n \nvec4 transition (vec2 uv) {\n  vec2 v = normalize(direction);\n  v /= abs(v.x)+abs(v.y);\n  float d = v.x * center.x + v.y * center.y;\n  float m =\n    (1.0-step(progress, 0.0)) * // there is something wrong with our formula that makes m not equals 0.0 with progress is 0.0\n    (1.0 - smoothstep(-smoothness, 0.0, v.x * uv.x + v.y * uv.y - (d-0.5+progress*(1.+smoothness))));\n  return mix(getFromColor(uv), getToColor(uv), m);\n}\n\nvoid main() { gl_FragColor = transition(vUv); }"});
