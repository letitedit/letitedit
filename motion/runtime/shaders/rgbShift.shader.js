/*
The MIT License

Copyright © 2010-2025 three.js authors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
*/
M.shader.define("rgbShift", {"kind": "filter", "defaults": {"amount": 0.005, "angle": 0.0}, "fragment": "\n\n\t\tuniform sampler2D tDiffuse;\n\t\tuniform float amount;\n\t\tuniform float angle;\n\n\t\tvarying vec2 vUv;\n\n\t\tvoid main() {\n\n\t\t\tvec2 offset = amount * vec2( cos(angle), sin(angle));\n\t\t\tvec4 cr = texture2D(tDiffuse, vUv + offset);\n\t\t\tvec4 cga = texture2D(tDiffuse, vUv);\n\t\t\tvec4 cb = texture2D(tDiffuse, vUv - offset);\n\t\t\tgl_FragColor = vec4(cr.r, cga.g, cb.b, cga.a);\n\n\t\t}"});
