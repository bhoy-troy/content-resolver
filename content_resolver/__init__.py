"""content_resolver package initialisation.

Sets the multiprocessing start method to ``'fork'`` before any other imports
so that libdnf5 / SWIG C objects are not required to be picklable.  Python
3.14+ switched the default to ``'forkserver'``, which requires pickling and
would break DNF5 object sharing across processes.

See: https://docs.python.org/3/whatsnew/3.14.html#concurrent-futures
"""

import multiprocessing

try:
    multiprocessing.set_start_method("fork")
except RuntimeError:
    # Already set, ignore
    pass
