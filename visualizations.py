#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Visualizations: 3D Vector Space + Detection Flow
Consolidated from: vector_space_3d.py, detection_flow_enhanced.py
"""


import plotly.graph_objects as go
import numpy as np
from typing import List, Dict, Optional

try:
    from config import Config
except Exception:
    class Config:
        ALLOW_DEMO_DATA = False

# Try to import DR libraries (optional dependencies)
try:
    from sklearn.decomposition import PCA
    from sklearn.manifold import TSNE
    _HAS_SKLEARN = True
except ImportError:
    _HAS_SKLEARN = False

try:
    from umap import UMAP
    _HAS_UMAP = True
except ImportError:
    _HAS_UMAP = False


def apply_dimensionality_reduction(
    embeddings: np.ndarray,
    method: str = "None",
    n_components: int = 3,
    random_state: int = 42
) -> Optional[np.ndarray]:
    """
    Apply dimensionality reduction to embeddings

    Args:
        embeddings: Input embeddings (n_samples, n_features)
        method: DR method ("None", "PCA", "t-SNE", "UMAP")
        n_components: Number of output dimensions (default: 3)
        random_state: Random seed for reproducibility

    Returns:
        Reduced embeddings or None if method is "None" or not available
    """
    if method == "None" or embeddings is None:
        return None

    if method == "PCA":
        if not _HAS_SKLEARN:
            print("⚠️ sklearn not available, falling back to spatial distribution")
            return None
        reducer = PCA(n_components=n_components, random_state=random_state)
        return reducer.fit_transform(embeddings)

    elif method == "t-SNE":
        if not _HAS_SKLEARN:
            print("⚠️ sklearn not available, falling back to spatial distribution")
            return None
        # t-SNE is slow, use perplexity based on sample size
        n_samples = embeddings.shape[0]
        perplexity = min(30, max(5, n_samples // 3))
        reducer = TSNE(n_components=n_components, random_state=random_state, perplexity=perplexity)
        return reducer.fit_transform(embeddings)

    elif method == "UMAP":
        if not _HAS_UMAP:
            print("⚠️ UMAP not available, falling back to spatial distribution")
            return None
        n_samples = embeddings.shape[0]
        n_neighbors = min(15, max(2, n_samples - 1))
        reducer = UMAP(n_components=n_components, random_state=random_state, n_neighbors=n_neighbors)
        return reducer.fit_transform(embeddings)

    return None


def _allow_demo_data() -> bool:
    return bool(getattr(Config, 'ALLOW_DEMO_DATA', False))


def _add_data_source_annotation(fig: go.Figure, message: str):
    fig.add_annotation(
        text=message,
        xref="paper",
        yref="paper",
        x=0.5,
        y=-0.16,
        showarrow=False,
        font=dict(size=11, color="#8a6d3b"),
        bgcolor="rgba(255, 243, 205, 0.9)",
        bordercolor="#ffc107",
        borderwidth=1,
        borderpad=6,
        align="center"
    )

def create_3d_vector_space_with_hover(
    problems: list = None,
    real_docs: list = None,
    num_docs: int = 20,
    show_boundaries: bool = True,
    show_distance_lines: bool = True,
    show_zone_red: bool = False,
    show_zone_yellow: bool = False,
    show_zone_green: bool = False,
    dr_method: str = "None",
    h2l_config = None,
    demo_mode: Optional[bool] = None
):
    """
    Creates an interactive 3D vector space visualization showing relationships between
    the query, detected problems, and retrieved documents.

    Features:
    - Real Query Semantic Topology (docs clustered near matched problems)
    - Hover shows: Document ID & Source, S_rerank, S_final, Distance
    """
    demo_mode = _allow_demo_data() if demo_mode is None else bool(demo_mode)

    # Lightweight default config if not provided
    if h2l_config is None:
        class DefaultVizConfig:
            ALPHA = 1.0
        h2l_config = DefaultVizConfig()

    fig = go.Figure()

    # Calculate problem priors
    if problems:
        total_severity = sum(p.get('severity', 1) for p in problems)
        for p in problems:
            p['prior'] = p.get('severity', 1) / total_severity

    # ==================== DIMENSIONALITY REDUCTION (if selected) ====================
    use_dr = dr_method != "None"
    dr_coords = None

    if use_dr and problems:
        if not demo_mode:
            print("⚠️ Dimensionality reduction requires real embeddings; synthetic DR is disabled.")
            use_dr = False
        else:
            # Demo-only synthetic embeddings for UI layout experiments.
            n_total = len(problems) + num_docs + 1
            embedding_dim = 768
            np.random.seed(42)
            embeddings = np.random.randn(n_total, embedding_dim) * 0.5
            embeddings[0] = np.zeros(embedding_dim)
            dr_coords = apply_dimensionality_reduction(embeddings, method=dr_method, n_components=3)

            if dr_coords is not None:
                print(f"✅ Applied {dr_method} dimensionality reduction on DEMO synthetic embeddings")
            else:
                print(f"⚠️ {dr_method} not available, using spatial distribution")
                use_dr = False

    # ==================== QUERY (Center) ====================
    if use_dr and dr_coords is not None:
        qx, qy, qz = dr_coords[0]
    else:
        qx, qy, qz = 0, 0, 0

    fig.add_trace(go.Scatter3d(
        x=[qx],
        y=[qy],
        z=[qz],
        mode='markers+text',
        marker=dict(
            size=16,
            color='#FFD700', # Gold/Yellow for Query
            symbol='diamond',
            line=dict(width=2, color='#B7950B') # Darker gold border for 3D depth
        ),
        text=['⭐ Query'],
        textposition='top center',
        textfont=dict(size=14, color='#F39C12', family='Arial Black'),
        name='⭐ Query',
        hovertemplate=f'<b>⭐ Query</b><br>Position: ({qx:.2f}, {qy:.2f}, {qz:.2f})<br>ศูนย์กลางการค้นหา<extra></extra>'
    ))

    # ==================== PROBLEMS (Diamonds) ====================
    problem_positions = []
    # Distinct qualitative colors for categories (instead of severity which overlaps)
    distinct_colors = ['#AB63FA', '#FFA15A', '#19D3F3', '#FF6692', '#B6E880', '#FF97FF', '#FECB52', '#00CC96']

    if problems:
        # Distribute problems in 3D spherical coordinates
        n_problems = len(problems)
        golden_ratio = (1 + np.sqrt(5)) / 2

        for i, problem in enumerate(problems):
            severity = problem.get('severity', 3)
            confidence = problem.get('confidence', 0.8)
            prior = problem.get('prior', 0.3)

            # Use DR coordinates if available, otherwise use golden spiral
            if use_dr and dr_coords is not None:
                px, py, pz = dr_coords[i + 1]  # +1 to skip query at index 0
            else:
                # Position based on confidence (closer = higher confidence)
                radius = 2.5 - (confidence * 1.5)

                # Use golden spiral for even distribution
                theta = 2 * np.pi * i / golden_ratio
                phi = np.arccos(1 - 2 * (i + 0.5) / n_problems)

                px = radius * np.sin(phi) * np.cos(theta)
                py = radius * np.sin(phi) * np.sin(theta)
                pz = radius * np.cos(phi)

            problem_positions.append((px, py, pz, severity, confidence, prior))

            size = 10 + severity * 2
            
            # Use Blue color for ALL problems to match the 🔷 emoji from the UI header
            # But vary the opacity or border slightly to maintain some 3D distinction
            color = '#3498DB' # Vibrant Blue

            hover_text = f"""<b>🔷 {problem.get('name', 'Problem')}</b><br>
Code: {problem.get('code', 'N/A')}<br>
Severity: {severity}/5<br>
P(p|q): {confidence:.2%} (Detection Confidence)<br>
P(p): {prior:.2%} (Prior Probability)<br>
Position: ({px:.2f}, {py:.2f}, {pz:.2f})"""

            fig.add_trace(go.Scatter3d(
                x=[px],
                y=[py],
                z=[pz],
                mode='markers+text',
                marker=dict(
                    size=size,
                    color=color,
                    symbol='diamond',
                    line=dict(width=1.5, color='#2980B9') # Dark blue border
                ),
                text=[f'{problem.get("code", "P")[:6]}'],
                textposition='top center',
                textfont=dict(size=11, color='#2980B9', family="Inter, sans-serif"),
                name=f"🔷 {problem.get('code', 'P')[:6]}",
                showlegend=True,
                hovertemplate=hover_text + '<extra></extra>'
            ))

    # ==================== DOCUMENTS (Semantic Topology / Real Docs) ====================
    relevant_docs = []
    irrelevant_docs = []

    if real_docs is not None:
        for i, doc in enumerate(real_docs):
            s_rerank = doc.get('s_rerank', 0.0)
            final_score = doc.get('final_score', 0.0)
            factors = doc.get('factors', [])
            doc_id = doc.get('id', f'doc_{i:03d}')
            doc_source = doc.get('source', '')
            
            # Map score to distance [ S_rerank=1 -> 0.5, S_rerank=0 -> 3.5 ]
            distance = max(0.5, 3.5 - 3.0 * s_rerank)
            
            # Find best problem match for direction
            best_code = None
            best_phi = -1.0
            p_doc_val = 0.0
            if factors:
                for f in factors:
                    if f.get('phi_i', 0) > best_phi:
                        best_phi = f.get('phi_i', 0)
                        best_code = f.get('code')
                        p_doc_val = f.get('p_doc', 0)
            
            direction = (0, 0, 0)
            if best_code and problems:
                for j, p in enumerate(problems):
                    if p.get('code') == best_code and j < len(problem_positions):
                        px, py, pz, _, _, _ = problem_positions[j]
                        norm = max(0.01, np.sqrt(px**2 + py**2 + pz**2))
                        direction = (px/norm, py/norm, pz/norm)
                        break
            
            if direction == (0,0,0):
                # Deterministic fallback direction; do not synthesize semantic evidence.
                golden_ratio = (1 + np.sqrt(5)) / 2
                theta = 2 * np.pi * (i + 1) / golden_ratio
                phi_ang = np.arccos(1 - 2 * ((i + 0.5) / max(len(real_docs), 1)))
                direction = (np.sin(phi_ang)*np.cos(theta), np.sin(phi_ang)*np.sin(theta), np.cos(phi_ang))
            
            # Add deterministic jitter to avoid overlap without introducing random evidence.
            jitter_scale = 0.2 + (0.3 * (1.0 - s_rerank))
            dx = direction[0] * distance + np.sin(i + 1) * jitter_scale * 0.35
            dy = direction[1] * distance + np.cos(i + 1) * jitter_scale * 0.35
            dz = direction[2] * distance + np.sin((i + 1) * 1.7) * jitter_scale * 0.25
            
            # Recalculate true distance for UI
            true_dist = np.sqrt(dx**2 + dy**2 + dz**2)
            
            # Is relevant if final_score > threshold or s_rerank is high
            is_relevant = final_score > 0.0 or s_rerank > 0.4
            
            # Relevant docs will ALWAYS be Green 🟢, Irrelevant will be White/Grey ⚪
            doc_color = '#2ECC71' if is_relevant else '#E0E0E0' 
            
            doc_data = {
                'x': dx, 'y': dy, 'z': dz,
                'id': doc_id,
                'source': doc_source,
                'distance': true_dist,
                'rerank_score': s_rerank,
                'problem_coverage': p_doc_val,
                'final_score': final_score,
                'best_code': best_code if best_code else 'None',
                'color': doc_color
            }
            
            if is_relevant:
                relevant_docs.append(doc_data)
            else:
                irrelevant_docs.append(doc_data)

    # Plot Relevant Documents
    if relevant_docs:
        hover_texts = []
        for doc in relevant_docs:
            source = doc.get('source', '')[:30] + ('...' if len(doc.get('source', '')) > 30 else '')
            hover_texts.append(f"""<b>📄 {doc['id']}</b><br>
<span style='color: green;'>✅ {source}</span><br>
━━━━━━━━━━━━━━━<br>
🎯 Target: {doc.get('best_code')}<br>
📊 S_rerank: {doc['rerank_score']:.4f}<br>
🎯 Max P(d|p): {doc['problem_coverage']:.4f}<br>
━━━━━━━━━━━━━━━<br>
<b>🏆 S_final: {doc['final_score']:.4f}</b>""")

        fig.add_trace(go.Scatter3d(
            x=[d['x'] for d in relevant_docs],
            y=[d['y'] for d in relevant_docs],
            z=[d['z'] for d in relevant_docs],
            mode='markers',
            marker=dict(
                size=[8 + d['final_score'] * 6 for d in relevant_docs],
                color='#2ECC71', # Green
                symbol='circle',
                line=dict(width=1, color='#27AE60'),
                opacity=0.95
            ),
            text=[d['id'] for d in relevant_docs],
            name='🟢 Relevant Docs',
            hovertemplate='%{customdata}<extra></extra>',
            customdata=hover_texts
        ))

    # Plot Irrelevant Documents
    if irrelevant_docs:
        hover_texts = []
        for doc in irrelevant_docs:
            source = doc.get('source', '')[:30] + ('...' if len(doc.get('source', '')) > 30 else '')
            hover_texts.append(f"""<b>📄 {doc['id']}</b><br>
<span style='color: gray;'>➖ {source}</span><br>
━━━━━━━━━━━━━━━<br>
🎯 Target: {doc.get('best_code')}<br>
📊 S_rerank: {doc['rerank_score']:.4f}<br>
🎯 Max P(d|p): {doc['problem_coverage']:.4f}<br>
━━━━━━━━━━━━━━━<br>
<b>📉 S_final: {doc['final_score']:.4f}</b>""")

        fig.add_trace(go.Scatter3d(
            x=[d['x'] for d in irrelevant_docs],
            y=[d['y'] for d in irrelevant_docs],
            z=[d['z'] for d in irrelevant_docs],
            mode='markers',
            marker=dict(
                size=6,
                color='#E0E0E0', # Very light grey / white
                symbol='circle',
                opacity=0.8,
                line=dict(width=1, color='#BDBDBD')
            ),
            text=[d['id'] for d in irrelevant_docs],
            name='⚪ Other Docs',
            hovertemplate='%{customdata}<extra></extra>',
            customdata=hover_texts
        ))

    # ==================== NEW: COLOR ZONES (360-degree proximity) - SELECTIVE ====================
    # Define distance thresholds
    red_radius = 1.5    # Close proximity
    yellow_radius = 3.0  # Medium distance
    green_radius = 4.5   # Far distance

    # Create spherical mesh (optimized resolution for faster rendering)
    u = np.linspace(0, 2 * np.pi, 15)  # Reduced from 30 to 15
    v = np.linspace(0, np.pi, 10)      # Reduced from 20 to 10

    # Red zone (innermost) - only if selected
    if show_zone_red:
        x_red = red_radius * np.outer(np.cos(u), np.sin(v))
        y_red = red_radius * np.outer(np.sin(u), np.sin(v))
        z_red = red_radius * np.outer(np.ones(np.size(u)), np.cos(v))

        fig.add_trace(go.Surface(
            x=x_red, y=y_red, z=z_red,
            colorscale=[[0, 'rgba(255,0,0,0.15)'], [1, 'rgba(255,0,0,0.15)']],
            showscale=False,
            showlegend=False,
            name='🔴 Close Zone',
            hovertemplate='<b>🔴 Close Proximity Zone</b><br>Distance: < %.1f<extra></extra>' % red_radius,
            opacity=0.2
        ))

    # Yellow zone (middle) - only if selected
    if show_zone_yellow:
        x_yellow = yellow_radius * np.outer(np.cos(u), np.sin(v))
        y_yellow = yellow_radius * np.outer(np.sin(u), np.sin(v))
        z_yellow = yellow_radius * np.outer(np.ones(np.size(u)), np.cos(v))

        fig.add_trace(go.Surface(
            x=x_yellow, y=y_yellow, z=z_yellow,
            colorscale=[[0, 'rgba(255,255,0,0.1)'], [1, 'rgba(255,255,0,0.1)']],
            showscale=False,
            showlegend=False,
            name='🟡 Medium Zone',
            hovertemplate='<b>🟡 Medium Distance Zone</b><br>Distance: %.1f - %.1f<extra></extra>' % (red_radius, yellow_radius),
            opacity=0.15
        ))

    # Green zone (outer) - only if selected
    if show_zone_green:
        x_green = green_radius * np.outer(np.cos(u), np.sin(v))
        y_green = green_radius * np.outer(np.sin(u), np.sin(v))
        z_green = green_radius * np.outer(np.ones(np.size(u)), np.cos(v))

        fig.add_trace(go.Surface(
            x=x_green, y=y_green, z=z_green,
            colorscale=[[0, 'rgba(0,255,0,0.08)'], [1, 'rgba(0,255,0,0.08)']],
            showscale=False,
            showlegend=False,
            name='🟢 Far Zone',
            hovertemplate='<b>🟢 Far Distance Zone</b><br>Distance: %.1f - %.1f<extra></extra>' % (yellow_radius, green_radius),
            opacity=0.12
        ))

    # ==================== NEW: DISTANCE LINES ====================
    if show_distance_lines and relevant_docs:
        # Sort by final score and get top 5
        top_docs = sorted(relevant_docs, key=lambda d: d['final_score'], reverse=True)[:5]

        for doc in top_docs:
            # Line from query (0,0,0) to document
            fig.add_trace(go.Scatter3d(
                x=[0, doc['x']],
                y=[0, doc['y']],
                z=[0, doc['z']],
                mode='lines',
                line=dict(
                    color='rgba(0, 100, 200, 0.8)',
                    width=3,
                    dash='dot'
                ),
                name='Distance Line',
                showlegend=False,
                hovertemplate=f'<b>📏 Distance Line</b><br>To: {doc["id"]}<br>Distance: {doc["distance"]:.3f}<extra></extra>'
            ))

    # Also add distance lines to problems if requested
    if show_distance_lines and problem_positions:
        for i, (px, py, pz, sev, conf, prior) in enumerate(problem_positions[:3]):  # Top 3 problems
            distance = np.sqrt(px**2 + py**2 + pz**2)
            fig.add_trace(go.Scatter3d(
                x=[0, px],
                y=[0, py],
                z=[0, pz],
                mode='lines',
                line=dict(
                    color='rgba(200, 50, 50, 0.8)',
                    width=4,
                    dash='solid'
                ),
                name='Problem Distance',
                showlegend=False,
                hovertemplate=f'<b>📏 Distance to Problem</b><br>Distance: {distance:.3f}<extra></extra>'
            ))

    # ==================== LAYOUT ====================
    fig.update_layout(
        title=dict(
            text='<b>🎯 H2L: 3D Vector Space Visualization</b><br><sub>Hover over points for detailed information</sub>',
            font=dict(size=16)
        ),
        scene=dict(
            xaxis=dict(
                title='Dimension 1',
                range=[-6, 6],
                showgrid=True,
                gridcolor='#f0f0f0',
                backgroundcolor='white'
            ),
            yaxis=dict(
                title='Dimension 2',
                range=[-6, 6],
                showgrid=True,
                gridcolor='#f0f0f0',
                backgroundcolor='white'
            ),
            zaxis=dict(
                title='Dimension 3',
                range=[-6, 6],
                showgrid=True,
                gridcolor='#f0f0f0',
                backgroundcolor='white'
            ),
            camera=dict(
                eye=dict(x=1.5, y=1.5, z=1.3),
                center=dict(x=0, y=0, z=0)
            )
        ),
        height=700,
        template='plotly_white',
        legend=dict(
            orientation='v',
            yanchor='top',
            y=0.99,
            xanchor='left',
            x=0.01
        ),
        hoverlabel=dict(
            bgcolor='white',
            font_size=11,
            font_family='Arial'
        ),
        margin=dict(b=80),
        annotations=[
            dict(
                text=(
                    "<b>🗺️ 3D Semantic Vector Space (Topology Mapping)</b><br>"
                    "กราฟนี้จำลองการกระจายตัวของเอกสาร (จุดเล็ก) รอบๆ ศูนย์กลางคำค้นหา (Query) และปัญหาทางสังคมที่เกี่ยวข้อง (จุดเพชร)<br>"
                    "<i>ระยะห่าง</i> สะท้อนถึงความคล้ายคลึงของข้อความ (ยิ่งใกล้ ยิ่งเกี่ยวข้อง) ส่วน <i>ทิศทางและสี</i> บ่งชี้ว่าเอกสารนั้นสัมพันธ์กับปัญหาใดมากที่สุด"
                ),
                xref="paper", yref="paper",
                x=0.5, y=-0.1,
                showarrow=False,
                font=dict(size=12, color="#555", family="Inter, sans-serif"),
                bgcolor="rgba(255,255,255,0.8)",
                bordercolor="#ccc",
                borderwidth=1,
                borderpad=8,
                align="center"
            )
        ]
    )

    if not real_docs:
        _add_data_source_annotation(
            fig,
            "No real retrieval documents were supplied. Synthetic document points are disabled by default."
        )
    elif demo_mode and use_dr:
        _add_data_source_annotation(
            fig,
            "DEMO MODE: dimensionality reduction used synthetic embeddings for layout only."
        )

    return fig


# =============================================================================
# Enhanced Detection Flow Visualization (from detection_flow_enhanced.py)
# =============================================================================


def create_detection_flow_visualization_enhanced(
    l1_count: int,
    l2_confirmed: int,
    l2_filtered: int,
    filtered_reasons: Optional[List[Dict]] = None,
    confirmed_reasons: Optional[List[Dict]] = None
) -> go.Figure:
    """
    Enhanced Detection Flow Diagram with detailed explanations

    Args:
        l1_count: Number of L1 candidates
        l2_confirmed: Number of L2 confirmed problems
        l2_filtered: Number of L2 filtered items
        filtered_reasons: List of dicts with 'code', 'name', 'reason' for filtered items
        confirmed_reasons: List of dicts with 'code', 'name', 'reason' for confirmed items

    Shows:
    - L1 Detection: What it does, tools used, output
    - L2 Validation: How it filters, results
    - Confirmed: Final count, precision, next steps, detailed reasons
    - Filtered: Why filtered, examples, detailed reasons
    """

    # Calculate metrics
    if l1_count > 0:
        precision_improvement = (l2_filtered / l1_count) * 100
        l2_precision = (l2_confirmed / l1_count) * 100
    else:
        precision_improvement = 0
        l2_precision = 0

    # Build detailed reasons text
    confirmed_details = ""
    if confirmed_reasons and len(confirmed_reasons) > 0:
        confirmed_details = "<br><br><b>📋 Confirmed Items:</b><br>"
        for i, item in enumerate(confirmed_reasons[:5], 1):  # Show top 5
            code = item.get('code', 'N/A')
            name = item.get('name', 'Unknown')
            reason = item.get('reason', 'High confidence match')
            confirmed_details += f"{i}. <b>{code}</b> - {name}<br>   → {reason}<br>"
        if len(confirmed_reasons) > 5:
            confirmed_details += f"   ... and {len(confirmed_reasons) - 5} more<br>"

    filtered_details = ""
    if filtered_reasons and len(filtered_reasons) > 0:
        filtered_details = "<br><br><b>📋 Filtered Items:</b><br>"
        for i, item in enumerate(filtered_reasons[:5], 1):  # Show top 5
            code = item.get('code', 'N/A')
            name = item.get('name', 'Unknown')
            reason = item.get('reason', 'Context mismatch')
            filtered_details += f"{i}. <b>{code}</b> - {name}<br>   → {reason}<br>"
        if len(filtered_reasons) > 5:
            filtered_details += f"   ... and {len(filtered_reasons) - 5} more<br>"

    fig = go.Figure(data=[go.Sankey(
        node=dict(
            pad=20,
            thickness=25,
            line=dict(color='black', width=0.5),
            label=[
                f'🔍 L1 Detection<br>(Keyword+Context)<br><b>{l1_count} candidates</b>',
                f'🧠 L2 Validation<br>(LLM Analysis)<br>Filter: {precision_improvement:.0f}%',
                f'✅ Confirmed<br><b>{l2_confirmed} problems</b><br>Precision: {l2_precision:.0f}%',
                f'❌ Filtered Out<br><b>{l2_filtered} false positives</b>'
            ],
            color=['#3498DB', '#9B59B6', '#27AE60', '#E74C3C'],
            customdata=[
                # L1 Detection
                f"<b>L1 Detection (Initial)</b><br>" +
                "━━━━━━━━━━━━━━━<br>" +
                f"<b>Method:</b> Keyword + Semantic matching<br>" +
                f"<b>Tools:</b> E5 embeddings + BM25<br>" +
                f"<b>Output:</b> {l1_count} candidates<br>" +
                f"<b>Threshold:</b> similarity > 0.7<br>" +
                f"<b>Note:</b> May contain false positives",

                # L2 Validation
                f"<b>L2 Validation (LLM Filter)</b><br>" +
                "━━━━━━━━━━━━━━━<br>" +
                f"<b>Method:</b> LLM context analysis<br>" +
                f"<b>Tools:</b> GPT-4 / Qwen2.5<br>" +
                f"<b>Result:</b> {l2_confirmed} confirmed + {l2_filtered} filtered<br>" +
                f"<b>Filter Rate:</b> {precision_improvement:.1f}%<br>" +
                f"<b>Beta:</b> β = 0.3 (L1/L2 weight)",

                # Confirmed
                f"<b>✅ Confirmed Problems</b><br>" +
                "━━━━━━━━━━━━━━━<br>" +
                f"<b>Count:</b> {l2_confirmed} problems<br>" +
                f"<b>Precision:</b> {l2_precision:.1f}%<br>" +
                f"<b>Usage:</b> Query expansion<br>" +
                f"<b>Next:</b> Probabilistic scoring<br>" +
                f"<b>Formula:</b> S_rerank · exp(α · Σ w_i · Φ_i) · P(rel)" +
                confirmed_details,

                # Filtered Out
                f"<b>❌ Filtered Out (False Positives)</b><br>" +
                "━━━━━━━━━━━━━━━<br>" +
                f"<b>Count:</b> {l2_filtered} items<br>" +
                f"<b>Reason:</b> Context mismatch<br>" +
                f"<b>Examples:</b> Word overlap, wrong meaning<br>" +
                f"<b>Status:</b> Not used in retrieval<br>" +
                f"<b>Impact:</b> Improves precision by {precision_improvement:.1f}%" +
                filtered_details
            ],
            hovertemplate='%{customdata}<extra></extra>'
        ),
        link=dict(
            source=[0, 1, 1],
            target=[1, 2, 3],
            value=[l1_count, l2_confirmed, l2_filtered],
            color=['rgba(52, 152, 219, 0.4)', 'rgba(39, 174, 96, 0.4)', 'rgba(231, 76, 60, 0.4)'],
            customdata=[
                f"<b>L1 → L2</b><br>Send {l1_count} candidates for LLM validation",
                f"<b>L2 → Confirmed</b><br>LLM confirms {l2_confirmed} are relevant",
                f"<b>L2 → Filtered</b><br>LLM filters {l2_filtered} false positives"
            ],
            hovertemplate='%{customdata}<extra></extra>'
        )
    )])

    fig.update_layout(
        title=dict(
            text=f'<b>🔍 H2L Detection Flow (2-Level Detection)</b><br><sub>{l1_count} candidates → {l2_confirmed} confirmed, {l2_filtered} filtered ({precision_improvement:.1f}% improvement)</sub>',
            font=dict(size=14)
        ),
        height=500,  # Increased from 450 for better horizontal layout
        font_size=12,
        annotations=[
            dict(
                text=f"<b>L2 Impact:</b> Precision +{precision_improvement:.1f}% | Recall ≈ {(l2_confirmed/max(l1_count, 1)*100):.1f}%",
                xref="paper", yref="paper",
                x=0.5, y=-0.1,
                showarrow=False,
                font=dict(size=11, color='#555')
            )
        ]
    )

    return fig
