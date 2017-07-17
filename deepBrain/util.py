"""
Collection of helper routines to set up variables on cpu
and apply weight decay.
"""
import re
import tensorflow as tf

# If a model is trained with multiple GPUs, prefix all Op names with tower_name
# to differentiate the operations. Note that this prefix is removed from the
# names of the summaries when visualizing a model.
TOWER_NAME = 'tower'


def _activation_summary(x):
  """
    Helper to create summaries for activations.
    Creates a summary that provides a histogram of activations.
    Creates a summary that measures the sparsity of activations.

    :x: Tensor

    :returns: nothing
  """
  # Remove 'tower_[0-9]/' from the name in case this is a multi-GPU training
  # session. This helps the clarity of presentation on tensorboard.
  tensor_name = re.sub('%s_[0-9]*/' % TOWER_NAME, '', x.op.name)
  tf.summary.histogram(tensor_name + '/activations', x)
  tf.summary.scalar(tensor_name + '/sparsity', tf.nn.zero_fraction(x))


def _variable_on_cpu(name, shape, initializer):
  """
    Helper to create a Variable stored on CPU memory.

    :name: name of the variable
    :shape: list of ints
    :initializer: initializer for Variable

    :returns: Variable Tensor
  """
  with tf.device('/cpu:0'):
    dtype = tf.float16 if FLAGS.use_fp16 else tf.float32
    var = tf.get_variable(name, shape, initializer=initializer, dtype=dtype)
  return var


def _variable_with_weight_decay(name, shape, stddev, wd):
  """
    Helper to create an initialized Variable with weight decay.
    Note that the Variable is initialized with a truncated normal distribution.
    A weight decay is added only if one is specified.

    :name: name of the variable
    :shape: list of ints
    :stddev: standard deviation of a truncated Gaussian
    :wd: add L2Loss weight decay multiplied by this float. If None, weight
         decay is not added for this Variable.

    :returns: Variable Tensor
  """
  dtype = tf.float16 if FLAGS.use_fp16 else tf.float32
  var = _variable_on_cpu(
      name,
      shape,
      tf.contrib.layers.variance_scaling_initializer(factor=2.0,
                                                     mode='FAN_IN',
                                                     uniform=False,
                                                     seed=None,
                                                     dtype=dtype))
  if wd is not None:
    weight_decay = tf.cast(tf.multiply(tf.nn.l2_loss(var),
                                       wd, name='weight_loss'),
                           tf.float32) # CTC loss is in float32
    tf.add_to_collection('losses', weight_decay)
  return var
