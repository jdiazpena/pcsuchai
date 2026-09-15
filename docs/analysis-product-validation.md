# Analysis-product validation

Full validation and saved-record reports now independently check the analysis
metadata attached to every configured plot, as well as its frozen recipe, mask,
axes, values, scale, image dimensions and geographic context.

Selected count, empty/available status, variable, coordinate view and map
minimum/maximum must match the exact saved selection. Time-availability plots
must record the earliest/latest selected UTC observations, or explicit nulls for
an empty selection. Duplicates remain observations; excluded times remain
excluded. Changing metadata without changing the retained arrays fails the audit.

Requested particle-weighted centroids are checked using an independent scalar
`math.fsum`/trigonometric reference, not by calling the production centroid
function. Latitude is an arithmetic weighted mean; longitude is a circular
weighted mean. This is a declared summary, not a spherical 3D centroid or a
physical SAA boundary estimate. Coordinates refer to the selected geographic,
magnetic or geographic-footpoint view; those views are not interchanged.

No positive finite weight, negative weights, non-finite selected coordinates or
a normalized circular resultant no larger than 64 float64 epsilons produces an
explicitly unavailable centroid. In particular, opposite equally weighted
longitudes must not turn floating-point roundoff into an arbitrary longitude.
The plot and original raw values remain retained with their original mask.

Production weights are normalized before multiplication. If a positive total
overflows float64, valid centroid coordinates remain available but the total is
null with `total_particle_count_status: overflow_float64`. Ordinary totals have
status `available`; old normal summaries without this extra status field remain
auditable. Undefined coordinates/total must be explicit null fields, not omitted.

The scalar-reference angular tolerance is 1e-10 degrees and the total-count
relative tolerance is 1e-12. These are numerical audit thresholds, not physical
location uncertainties or independently verified orbit/magnetic-model accuracy.
The reference uses the exact saved filtered rows and coordinates, so this check
cannot certify the correctness of an orbit solely by agreeing with its centroid.
