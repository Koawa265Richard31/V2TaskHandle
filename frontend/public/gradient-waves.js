// GradientWaves WebGL 背景(ReactBits 移植,原生 WebGL2,无 ogl 依赖)
// 暗色主题紫色,亮色主题蓝色。主题切换时更新 shader 颜色。
(function () {
  const canvas = document.getElementById('gradient-waves');
  if (!canvas) return;

  const gl = canvas.getContext('webgl2', { alpha: true, premultipliedAlpha: true, antialias: false });
  if (!gl) return;

  const hexToRgb = hex => {
    const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    if (!result) return [1, 1, 1];
    return [parseInt(result[1], 16) / 255, parseInt(result[2], 16) / 255, parseInt(result[3], 16) / 255];
  };

  const vertex = `#version 300 es
  in vec2 position;
  void main() { gl_Position = vec4(position, 0.0, 1.0); }
  `;

  const fragment = `#version 300 es
  precision highp float;
  uniform vec2 iResolution;
  uniform float iTime;
  uniform float uSpeed;
  uniform float uAmplitude;
  uniform float uWaveScale;
  uniform float uWaveRatio;
  uniform float uSwell;
  uniform float uTurbulence;
  uniform float uTilt;
  uniform float uZoom;
  uniform float uHeight;
  uniform float uFogDepth;
  uniform float uSteps;
  uniform float uBrightness;
  uniform float uOpacity;
  uniform vec3 uHorizonColor;
  uniform vec3 uWaveColor;
  uniform vec3 uCrestColor;
  out vec4 fragColor;
  const float MAX_DIST = 20000.0;

  float hash21(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
  }

  float plasma(vec3 r, vec2 freq, vec4 tc) {
    float mx = r.x + tc.x;
    mx += uSwell * sin((r.y + mx) / 20.0 + tc.y);
    float my = r.y - tc.z;
    my += uTurbulence * cos(r.x / 23.0 + tc.w);
    return r.z - (sin(mx * freq.x) * uAmplitude + sin(my * freq.y) * uAmplitude + uHeight);
  }

  float raymarch(vec3 pos, vec3 dir, vec2 freq, vec4 tc) {
    float dist = 0.0;
    for (int i = 0; i < 128; i++) {
      if (float(i) >= uSteps) break;
      float dscene = plasma(pos + dist * dir, freq, tc);
      if (abs(dscene) < 0.1) break;
      dist += 0.9 * dscene;
      if (!(abs(dist) < MAX_DIST)) return MAX_DIST;
    }
    return dist;
  }

  void main() {
    float T = iTime * uSpeed;
    vec2 freq = vec2(uWaveScale / 7.0, (uWaveScale * uWaveRatio) / 3.0);
    vec4 tc = vec4(T / 0.130, T / 0.810, T / 0.200, T / 0.710);
    float c, s;
    float vfov = (3.14159 / 2.3) / max(uZoom, 0.05);
    vec3 cam = vec3(0.0, 0.0, 30.0);
    // 以固定 16:9 为参考纵横比归一化,避免波浪形态随窗口纵横比变化
    const float REF_ASPECT = 16.0 / 9.0;
    vec2 uv = (gl_FragCoord.xy / iResolution.xy) - 0.5;
    uv.x *= REF_ASPECT;
    uv.y *= -1.0;
    vec3 dir = vec3(0.0, 0.0, -1.0);
    float ulen = length(uv);
    float xrot = vfov * ulen;
    c = cos(xrot); s = sin(xrot);
    dir = mat3(1.0, 0.0, 0.0, 0.0, c, -s, 0.0, s, c) * dir;
    vec2 nuv = ulen > 1e-5 ? uv / ulen : vec2(1.0, 0.0);
    c = nuv.x; s = nuv.y;
    dir = mat3(c, -s, 0.0, s, c, 0.0, 0.0, 0.0, 1.0) * dir;
    c = cos(uTilt); s = sin(uTilt);
    dir = mat3(c, 0.0, s, 0.0, 1.0, 0.0, -s, 0.0, c) * dir;
    float dist = raymarch(cam, dir, freq, tc);
    vec3 pos = cam + dist * dir;
    float t = clamp(pow(uFogDepth / max(dist, 0.001), 0.7), 0.0, 1.0);
    vec3 body = mix(uWaveColor, uCrestColor, clamp(pos.z * 0.15 + 0.4, 0.0, 1.0));
    vec3 col = mix(uHorizonColor, body, t);
    col *= uBrightness;
    col = clamp(col, 0.0, 1.0);
    float alpha = clamp(t, 0.0, 1.0) * uOpacity;
    // 顶部渐隐:canvas 顶部 18% 平滑淡出,与页面背景融合,避免生硬边界
    float ny = gl_FragCoord.y / iResolution.y;
    float fade = 1.0 - smoothstep(0.82, 1.0, ny);
    alpha *= fade;
    fragColor = vec4(col * alpha, alpha);
  }
  `;

  // 编译 shader
  function compile(type, src) {
    const sh = gl.createShader(type);
    gl.shaderSource(sh, src);
    gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
      console.error(gl.getShaderInfoLog(sh));
      return null;
    }
    return sh;
  }

  const vs = compile(gl.VERTEX_SHADER, vertex);
  const fs = compile(gl.FRAGMENT_SHADER, fragment);
  const program = gl.createProgram();
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    console.error(gl.getProgramInfoLog(program));
    return;
  }
  gl.useProgram(program);

  // Fullscreen triangle
  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const posLoc = gl.getAttribLocation(program, 'position');
  gl.enableVertexAttribArray(posLoc);
  gl.vertexAttribPointer(posLoc, 2, gl.FLOAT, false, 0, 0);

  // uniforms
  const u = {};
  ['iResolution','iTime','uSpeed','uAmplitude','uWaveScale','uWaveRatio','uSwell','uTurbulence',
   'uTilt','uZoom','uHeight','uFogDepth','uSteps','uBrightness','uOpacity',
   'uHorizonColor','uWaveColor','uCrestColor'].forEach(n => { u[n] = gl.getUniformLocation(program, n); });

  // 主题配色:暗色紫 / 亮色蓝
  const THEMES = {
    dark:  { horizon: '#1a0f3d', wave: '#5b3fc0', crest: '#d8ccff' },
    light: { horizon: '#075985', wave: '#0369a1', crest: '#0ea5e9' },
  };

  function setThemeColors(theme) {
    const c = THEMES[theme] || THEMES.dark;
    const h = hexToRgb(c.horizon), w = hexToRgb(c.wave), cr = hexToRgb(c.crest);
    gl.uniform3f(u.uHorizonColor, h[0], h[1], h[2]);
    gl.uniform3f(u.uWaveColor, w[0], w[1], w[2]);
    gl.uniform3f(u.uCrestColor, cr[0], cr[1], cr[2]);
    // 暗色背景深,低 alpha 已有对比;亮色白底 alpha 低会被稀释到几乎看不见,
    // 故亮色提高 opacity 让深蓝波浪清晰,同时降 brightness 保留深蓝本身
    if (theme === 'light') {
      gl.uniform1f(u.uBrightness, 1.0);
      gl.uniform1f(u.uOpacity, 3.0);
    } else {
      gl.uniform1f(u.uBrightness, 2.2);
      gl.uniform1f(u.uOpacity, 1.0);
    }
  }

  // 参数(与 ReactBits 默认接近)
  gl.uniform1f(u.uSpeed, 0.4);
  gl.uniform1f(u.uAmplitude, 2.5);
  gl.uniform1f(u.uWaveScale, 0.6);
  gl.uniform1f(u.uWaveRatio, 0.9);
  gl.uniform1f(u.uSwell, 35);
  gl.uniform1f(u.uTurbulence, 20);
  gl.uniform1f(u.uTilt, 0.85);
  gl.uniform1f(u.uZoom, 1.0);
  gl.uniform1f(u.uHeight, 3.0);
  gl.uniform1f(u.uFogDepth, 5);
  gl.uniform1f(u.uSteps, 70.0);
  gl.uniform1f(u.uBrightness, 2.2);
  gl.uniform1f(u.uOpacity, 1.0);

  const initial = document.documentElement.getAttribute('data-theme') || 'dark';
  setThemeColors(initial);

  // 窗口尺寸
  function resize() {
    const rect = canvas.getBoundingClientRect();
    const w = Math.max(1, Math.floor(rect.width));
    const h = Math.max(1, Math.floor(rect.height));
    canvas.width = Math.floor(w * Math.min(window.devicePixelRatio || 1, 2));
    canvas.height = Math.floor(h * Math.min(window.devicePixelRatio || 1, 2));
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.uniform2f(u.iResolution, canvas.width, canvas.height);
  }
  window.addEventListener('resize', resize);
  resize();

  // 动画循环
  const t0 = performance.now();
  function loop(t) {
    gl.uniform1f(u.iTime, (t - t0) * 0.001);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);

  // 主题切换监听:更新 shader 颜色
  const observer = new MutationObserver(() => {
    const theme = document.documentElement.getAttribute('data-theme') || 'dark';
    setThemeColors(theme);
  });
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
})();
