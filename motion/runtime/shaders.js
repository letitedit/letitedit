(function (M) {
  'use strict';
  const definitions = new Map();
  const programs = new Map();
  const canvas = document.createElement('canvas');
  let context;
  let failure = '';
  const vertex = 'attribute vec2 position; varying vec2 vUv; void main() { vUv = position * 0.5 + 0.5; gl_Position = vec4(position, 0.0, 1.0); }';
  const api = {last: {ok: false, reason: 'not drawn'}};

  function graphics() {
    if (context === undefined) {
      try {
        context = canvas.getContext('webgl', {alpha: true, premultipliedAlpha: false, preserveDrawingBuffer: true});
        if (!context) failure = 'WebGL unavailable';
      } catch (error) {
        failure = String(error.message || error);
        context = null;
      }
    }
    if (!context || context.isContextLost()) throw new Error(failure || 'WebGL context lost');
    return context;
  }

  function compile(gl, type, source) {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      const message = gl.getShaderInfoLog(shader);
      gl.deleteShader(shader);
      throw new Error(message || 'shader compilation failed');
    }
    return shader;
  }

  function program(gl, name, definition) {
    if (programs.has(name)) return programs.get(name);
    const compiled = [];
    let linked;
    try {
      compiled.push(compile(gl, gl.VERTEX_SHADER, vertex));
      compiled.push(compile(gl, gl.FRAGMENT_SHADER, 'precision highp float;\n' + definition.fragment));
      linked = gl.createProgram();
      compiled.forEach(shader => gl.attachShader(linked, shader));
      gl.linkProgram(linked);
      if (!gl.getProgramParameter(linked, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(linked) || 'shader link failed');
      const buffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
      const uniforms = [];
      for (let index = 0; index < gl.getProgramParameter(linked, gl.ACTIVE_UNIFORMS); index++) {
        const info = gl.getActiveUniform(linked, index);
        uniforms.push({name: info.name, type: info.type, location: gl.getUniformLocation(linked, info.name)});
      }
      const result = {linked, buffer, uniforms, textures: []};
      programs.set(name, result);
      return result;
    } catch (error) {
      if (linked) gl.deleteProgram(linked);
      throw error;
    } finally {
      compiled.forEach(shader => gl.deleteShader(shader));
    }
  }

  function texture(gl, entry, index, image) {
    if (!image) throw new Error('shader input image missing');
    const value = entry.textures[index] || (entry.textures[index] = gl.createTexture());
    gl.activeTexture(gl.TEXTURE0 + index);
    gl.bindTexture(gl.TEXTURE_2D, value);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
  }

  function fallback(g, definition, options, rect) {
    const {x, y, width, height} = rect;
    if (definition.kind === 'background') {
      const color = options.colorA || [0.08, 0.12, 0.22];
      g.fillStyle = 'rgb(' + color.map(value => Math.round(Math.max(0, Math.min(1, value)) * 255)).join(',') + ')';
      g.fillRect(x, y, width, height);
    } else if (definition.kind === 'transition' && options.from && options.to) {
      g.clearRect(x, y, width, height);
      const alpha = g.globalAlpha;
      g.globalAlpha = alpha * (1 - options.progress);
      g.drawImage(options.from, x, y, width, height);
      g.globalCompositeOperation = 'lighter';
      g.globalAlpha = alpha * options.progress;
      g.drawImage(options.to, x, y, width, height);
    } else if (options.source && options.source !== g.canvas) {
      g.clearRect(x, y, width, height);
      g.drawImage(options.source, x, y, width, height);
    }
  }

  function draw(name, g, time, supplied = {}) {
    const definition = definitions.get(name);
    const options = Object.assign({}, definition.defaults, supplied);
    options.progress = Math.max(0, Math.min(1, Number(options.progress) || 0));
    const rect = {x: options.x || 0, y: options.y || 0,
      width: Math.max(1, Math.round(options.width || g.canvas.width)),
      height: Math.max(1, Math.round(options.height || g.canvas.height))};
    g.save();
    try {
      const gl = graphics();
      if (canvas.width !== rect.width || canvas.height !== rect.height) {
        canvas.width = rect.width;
        canvas.height = rect.height;
      }
      const entry = program(gl, name, definition);
      gl.useProgram(entry.linked);
      gl.bindBuffer(gl.ARRAY_BUFFER, entry.buffer);
      const position = gl.getAttribLocation(entry.linked, 'position');
      gl.enableVertexAttribArray(position);
      gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
      gl.viewport(0, 0, rect.width, rect.height);
      gl.disable(gl.BLEND);
      const values = Object.assign({}, options, {time: Number(time) || 0, ratio: rect.width / rect.height});
      let textureIndex = 0;
      for (const uniform of entry.uniforms) {
        if (uniform.type === gl.SAMPLER_2D) {
          const image = uniform.name === 'tFrom' ? options.from : uniform.name === 'tTo' ? options.to : (options.source || g.canvas);
          texture(gl, entry, textureIndex, image);
          gl.uniform1i(uniform.location, textureIndex++);
        } else {
          const value = values[uniform.name];
          if (value === undefined) throw new Error('shader uniform missing: ' + uniform.name);
          if (uniform.type === gl.FLOAT) gl.uniform1f(uniform.location, value);
          else if (uniform.type === gl.BOOL || uniform.type === gl.INT) gl.uniform1i(uniform.location, Number(value));
          else if (uniform.type === gl.FLOAT_VEC2) gl.uniform2fv(uniform.location, value);
          else if (uniform.type === gl.FLOAT_VEC3) gl.uniform3fv(uniform.location, value);
          else if (uniform.type === gl.FLOAT_VEC4) gl.uniform4fv(uniform.location, value);
          else throw new Error('shader uniform type unsupported: ' + uniform.name);
        }
      }
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      if (gl.getError() !== gl.NO_ERROR || gl.isContextLost()) throw new Error('WebGL draw failed');
      g.clearRect(rect.x, rect.y, rect.width, rect.height);
      g.drawImage(canvas, rect.x, rect.y, rect.width, rect.height);
      api.last = {ok: true, name, renderer: 'WebGL'};
    } catch (error) {
      fallback(g, definition, options, rect);
      api.last = {ok: false, name, reason: String(error.message || error), renderer: '2D fallback'};
    } finally {
      g.restore();
    }
    return api.last;
  }

  api.define = function (name, definition) {
    if (Object.prototype.hasOwnProperty.call(api, name)) throw new Error('duplicate shader: ' + name);
    definitions.set(name, definition);
    api[name] = (g, time, options) => draw(name, g, time, options);
  };
  canvas.addEventListener('webglcontextlost', event => {
    event.preventDefault();
    failure = 'WebGL context lost';
    programs.clear();
  });
  canvas.addEventListener('webglcontextrestored', () => { failure = ''; programs.clear(); });
  M.shader = api;
})(window.M);
