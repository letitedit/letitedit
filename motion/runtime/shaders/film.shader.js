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
M.shader.define("film", {"kind": "filter", "defaults": {"intensity": 0.5, "grayscale": false}, "fragment": "\n\n\t\tfloat rand(vec2 p) { return fract(sin(dot(p, vec2(12.9898,78.233))) * 43758.5453); }\nfloat luminance(vec3 p) { return dot(p, vec3(0.2126,0.7152,0.0722)); }\n\n\t\tuniform float intensity;\n\t\tuniform bool grayscale;\n\t\tuniform float time;\n\n\t\tuniform sampler2D tDiffuse;\n\n\t\tvarying vec2 vUv;\n\n\t\tvoid main() {\n\n\t\t\tvec4 base = texture2D( tDiffuse, vUv );\n\n\t\t\tfloat noise = rand( fract( vUv + time ) );\n\n\t\t\tvec3 color = base.rgb + base.rgb * clamp( 0.1 + noise, 0.0, 1.0 );\n\n\t\t\tcolor = mix( base.rgb, color, intensity );\n\n\t\t\tif ( grayscale ) {\n\n\t\t\t\tcolor = vec3( luminance( color ) ); // assuming linear-srgb\n\n\t\t\t}\n\n\t\t\tgl_FragColor = vec4( color, base.a );\n\n\t\t}"});
