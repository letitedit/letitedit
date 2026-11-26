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
M.shader.define("filmBurn", {"kind": "transition", "defaults": {"Seed": 2.31}, "fragment": "uniform sampler2D tFrom; uniform sampler2D tTo; uniform float progress; uniform float ratio; varying vec2 vUv;\nvec4 getFromColor(vec2 uv) { return texture2D(tFrom, uv); }\nvec4 getToColor(vec2 uv) { return texture2D(tTo, uv); }\n// Author: Anastasia Dunbar\n// License: MIT\n// Description: Glowing film-burn light leaks wash over the image and reveal the incoming one\n// Tags: burn, film, light-leak\n// @param Random seed\nuniform float Seed; // = 2.31\nfloat sigmoid(float x, float a) {\n    float b = pow(x*2.,a)/2.;\n    if (x > .5) {\n        b = 1.-pow(2.-(x*2.),a)/2.;\n    }\n\treturn b;\n}\nfloat rand(float co){\n    return fract(sin((co*24.9898)+Seed)*43758.5453);\n}\nfloat rand(vec2 co){\n    return fract(sin(dot(co.xy ,vec2(12.9898,78.233))) * 43758.5453);\n}\nfloat apow(float a,float b) { return pow(abs(a),b)*sign(b); }\nvec3 pow3(vec3 a,vec3 b) { return vec3(apow(a.r,b.r),apow(a.g,b.g),apow(a.b,b.b)); }\nfloat smooth_mix(float a,float b,float c) { return mix(a,b,sigmoid(c,2.)); }\nfloat random(vec2 co, float shft){\n    co += 10.;\n    return smooth_mix(fract(sin(dot(co.xy ,vec2(12.9898+(floor(shft)*.5),78.233+Seed))) * 43758.5453),fract(sin(dot(co.xy ,vec2(12.9898+(floor(shft+1.)*.5),78.233+Seed))) * 43758.5453),fract(shft));\n}\nfloat smooth_random(vec2 co, float shft) {\n\treturn smooth_mix(smooth_mix(random(floor(co),shft),random(floor(co+vec2(1.,0.)),shft),fract(co.x)),smooth_mix(random(floor(co+vec2(0.,1.)),shft),random(floor(co+vec2(1.,1.)),shft),fract(co.x)),fract(co.y));\n}\nvec4 blendedColor(vec2 p) {\n    return mix(getFromColor(p), getToColor(p), sigmoid(progress,10.));\n}\n#define pi 3.14159265358979323\n#define clamps(x) clamp(x,0.,1.)\n\nvec4 transition(vec2 p) {\n  vec3 f = vec3(0.);\n  for (float i = 0.; i < 13.; i++) {\n    f += sin(((p.x*rand(i)*6.)+(progress*8.))+rand(i+1.43))*sin(((p.y*rand(i+4.4)*6.)+(progress*6.))+rand(i+2.4));\n    f += 1.-clamps(length(p-vec2(smooth_random(vec2(progress*1.3),i+1.),smooth_random(vec2(progress*.5),i+6.25)))*mix(20.,70.,rand(i)));\n  }\n  f += 4.;\n  f /= 11.;\n  f = pow3(f*vec3(1.,0.7,0.6),vec3(1.,2.-sin(progress*pi),1.3));\n  f *= sin(progress*pi);\n  \n  p -= .5;\n  p *= 1.+(smooth_random(vec2(progress*5.),6.3)*sin(progress*pi)*.05);\n  p += .5;\n  \n  vec4 blurred_image = vec4(0.);\n  float bluramount = sin(progress*pi)*.03;\n  #define repeats  50.\n  for (float i = 0.; i < repeats; i++) { \n      vec2 q = vec2(cos(degrees((i/repeats)*360.)),sin(degrees((i/repeats)*360.))) *  (rand(vec2(i,p.x+p.y))+bluramount); \n      vec2 uv2 = p+(q*bluramount);\n      blurred_image += blendedColor(uv2);\n  }\n  blurred_image /= repeats;\n  \n  return blurred_image+vec4(f,0.);\n}\n\nvoid main() { gl_FragColor = transition(vUv); }"});
