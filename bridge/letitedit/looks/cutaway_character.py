"""General cutaway properties; semantic character is explicitly caller-reviewed."""
import statistics


def reviewed_character(review):
    shots = review.get('shots', [])
    labelled = [shot for shot in shots if shot.get('character') is not None]
    if any(shot['character'] not in ('literal', 'idea_feeling', 'unknown') for shot in labelled):
        raise ValueError('shot character must be literal, idea_feeling or unknown')
    measurements = [shot['picture_properties'] for shot in shots if shot.get('picture_properties')]
    return {'reviewed_shots': len(labelled), 'total_shots': len(shots),
            'idea_feeling_share': sum(shot['character'] == 'idea_feeling' for shot in labelled) / len(labelled) if labelled else None,
            'literal_share': sum(shot['character'] == 'literal' for shot in labelled) / len(labelled) if labelled else None,
            'median_luma': statistics.median(row['median_luma'] for row in measurements) if measurements else None,
            'median_saturation': statistics.median(row['median_saturation'] for row in measurements) if measurements else None,
            'semantic_basis': 'caller-reviewed shot character, not inferred from pixel colour'}
