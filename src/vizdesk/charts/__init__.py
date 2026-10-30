"""Chart renderers. Importing this package registers every chart."""

from vizdesk.charts.base import REGISTRY, Renderer, chart  # noqa: F401
from vizdesk.charts import specialist, standard, structures  # noqa: F401,E402  (registers charts)
