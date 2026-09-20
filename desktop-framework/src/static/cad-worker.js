importScripts('/static/vendor/occt/occt-import-js.js');
self.onmessage = async ({data}) => {
  try {
    const response = await fetch(data.url);
    if (!response.ok) throw new Error('模型文件读取失败：' + response.status);
    const bytes = new Uint8Array(await response.arrayBuffer());
    self.postMessage({progress: '正在使用 OpenCascade 转换 CAD 曲面…'});
    const occt = await occtimportjs({locateFile: name => '/static/vendor/occt/' + name});
    const ext = data.format.toLowerCase();
    const read = ['igs','iges'].includes(ext) ? 'ReadIgesFile' : ext === 'brep' ? 'ReadBrepFile' : 'ReadStepFile';
    const result = occt[read](bytes, {linearUnit:'millimeter', linearDeflectionType:'bounding_box_ratio', linearDeflection:0.002, angularDeflection:0.5});
    if (!result.success || !result.meshes?.length) throw new Error('CAD 中没有成功转换的曲面');
    self.postMessage({result});
  } catch (e) { self.postMessage({error: e.message}); }
};
