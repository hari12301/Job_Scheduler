// Interactive DAG Visualizer

function renderDAG(containerId, nodes, edges) {
  const container = document.getElementById(containerId);
  if (!container) return;

  container.innerHTML = '';
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('width', '100%');
  svg.setAttribute('height', '340');
  svg.style.background = '#090d16';
  svg.style.borderRadius = '8px';
  svg.style.border = '1px solid #1e293b';

  // Define arrow marker
  const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
  const marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
  marker.setAttribute('id', 'arrow');
  marker.setAttribute('viewBox', '0 0 10 10');
  marker.setAttribute('refX', '10');
  marker.setAttribute('refY', '5');
  marker.setAttribute('markerWidth', '6');
  marker.setAttribute('markerHeight', '6');
  marker.setAttribute('orient', 'auto-start-reverse');
  
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', 'M 0 0 L 10 5 L 0 10 z');
  path.setAttribute('fill', '#64748b');
  marker.appendChild(path);
  defs.appendChild(marker);
  svg.appendChild(defs);

  // Position nodes horizontally
  const nodeWidth = 170;
  const nodeHeight = 54;
  const startX = 40;
  const gapX = 220;
  const startY = 140;

  const nodePositions = {};
  nodes.forEach((node, i) => {
    nodePositions[node.id] = {
      x: startX + (i * gapX),
      y: startY + (i % 2 === 0 ? -30 : 30)
    };
  });

  // Render Edges
  edges.forEach(edge => {
    const src = nodePositions[edge.source];
    const tgt = nodePositions[edge.target];
    if (src && tgt) {
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      const startPointX = src.x + nodeWidth;
      const startPointY = src.y + (nodeHeight / 2);
      const endPointX = tgt.x;
      const endPointY = tgt.y + (nodeHeight / 2);
      const midX = (startPointX + endPointX) / 2;

      const d = `M ${startPointX} ${startPointY} C ${midX} ${startPointY}, ${midX} ${endPointY}, ${endPointX} ${endPointY}`;
      line.setAttribute('d', d);
      line.setAttribute('stroke', '#475569');
      line.setAttribute('stroke-width', '2');
      line.setAttribute('fill', 'none');
      line.setAttribute('marker-end', 'url(#arrow)');
      svg.appendChild(line);
    }
  });

  // Render Node Cards
  nodes.forEach(node => {
    const pos = nodePositions[node.id];
    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    g.style.cursor = 'pointer';

    // Status colors
    let statusColor = '#f59e0b';
    if (node.status === 'COMPLETED') statusColor = '#10b981';
    if (node.status === 'RUNNING') statusColor = '#3b82f6';
    if (node.status === 'FAILED' || node.status === 'DEAD_LETTER') statusColor = '#ef4444';

    const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    rect.setAttribute('x', pos.x);
    rect.setAttribute('y', pos.y);
    rect.setAttribute('width', nodeWidth);
    rect.setAttribute('height', nodeHeight);
    rect.setAttribute('rx', '8');
    rect.setAttribute('fill', '#111827');
    rect.setAttribute('stroke', statusColor);
    rect.setAttribute('stroke-width', '1.5');
    g.appendChild(rect);

    // Node Title
    const textTitle = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    textTitle.setAttribute('x', pos.x + 12);
    textTitle.setAttribute('y', pos.y + 22);
    textTitle.setAttribute('fill', '#f8fafc');
    textTitle.setAttribute('font-size', '12');
    textTitle.setAttribute('font-weight', 'bold');
    textTitle.textContent = node.name.length > 18 ? node.name.substring(0, 18) + '...' : node.name;
    g.appendChild(textTitle);

    // Node Status
    const textStatus = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    textStatus.setAttribute('x', pos.x + 12);
    textStatus.setAttribute('y', pos.y + 42);
    textStatus.setAttribute('fill', statusColor);
    textStatus.setAttribute('font-size', '11');
    textStatus.setAttribute('font-weight', '600');
    textStatus.textContent = `● ${node.status}`;
    g.appendChild(textStatus);

    svg.appendChild(g);
  });

  container.appendChild(svg);
}

