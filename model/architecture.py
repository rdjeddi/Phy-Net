
"""functions used to construct different architectures  
"""

import tensorflow as tf
import numpy as np
import BasicConvLSTMCell

FLAGS = tf.app.flags.FLAGS

def _activation_summary(x):
  """Helper to create summaries for activations.

  Creates a summary that provides a histogram of activations.
  Creates a summary that measure the sparsity of activations.

  Args:
    x: Tensor
  Returns:
    nothing
  """
  tensor_name = x.op.name
  tf.histogram_summary(tensor_name + '/activations', x)
  tf.scalar_summary(tensor_name + '/sparsity', tf.nn.zero_fraction(x))

def _variable(name, shape, stddev):
  """Helper to create a Variable.

  Args:
    name: name of the variable
    shape: list of ints
    initializer: initializer for Variable

  Returns:
    Variable Tensor
  """
  var = tf.get_variable(name, shape, tf.truncated_normal_initializer(stddev=stddev))
  return var

def conv_layer(inputs, kernel_size, stride, num_features, idx, nonlinearity=None):
  with tf.variable_scope('{0}_conv'.format(idx)) as scope:
    input_channels = inputs.get_shape()[3]

    weights = _variable('weights', shape=[kernel_size,kernel_size,input_channels,num_features],stddev=0.01)
    biases = _variable('biases',[num_features],stddev=0.01)

    conv = tf.nn.conv2d(inputs, weights, strides=[1, stride, stride, 1], padding='SAME')
    conv_biased = tf.nn.bias_add(conv, biases)
    if nonlinearity is not None:
      conv_biased = nonlinearity(conv_biased)
    return conv_biased

def transpose_conv_layer(inputs, kernel_size, stride, num_features, idx, nonlinearity=None):
  with tf.variable_scope('{0}_trans_conv'.format(idx)) as scope:
    input_channels = inputs.get_shape()[3]
    
    weights = _variable('weights', shape=[kernel_size,kernel_size,num_features,input_channels], stddev=0.01)
    biases = _variable('biases',[num_features],stddev=0.01)
    batch_size = tf.shape(inputs)[0]
    output_shape = tf.pack([tf.shape(inputs)[0], tf.shape(inputs)[1]*stride, tf.shape(inputs)[2]*stride, num_features]) 
    conv = tf.nn.conv2d_transpose(inputs, weights, output_shape, strides=[1,stride,stride,1], padding='SAME')
    conv_biased = tf.nn.bias_add(conv, biases)
    if nonlinearity is not None:
      conv_biased = nonlinearity(conv_biased)
    return conv_biased

def fc_layer(inputs, hiddens, idx, flat = False, linear = False):
  with tf.variable_scope('{0}_fc'.format(idx)) as scope:
    input_shape = inputs.get_shape().as_list()
    if flat:
      dim = input_shape[1]*input_shape[2]*input_shape[3]
      inputs_processed = tf.reshape(inputs, [-1,dim])
    else:
      dim = input_shape[1]
      inputs_processed = inputs
    
    weights = _variable('weights', shape=[dim,hiddens],stddev=0.01)
    biases = _variable_on_cpu('biases', [hiddens], tf.constant_initializer(0.01))
    output_biased = tf.add(tf.matmul(inputs_processed,weights),biases,name=str(idx)+'_fc')
    if nonlinearity is not None:
      ouput_biased = nonlinearity(ouput_biased)
    return ouput_biased

def _phase_shift(I, r):
  bsize, a, b, c = I.get_shape().as_list()
  bsize = tf.shape(I)[0] # Handling Dimension(None) type for undefined batch dim
  X = tf.reshape(I, (bsize, a, b, r, r))
  X = tf.transpose(X, (0, 1, 2, 4, 3))  # bsize, a, b, 1, 1
  X = tf.split(1, a, X)  # a, [bsize, b, r, r]
  X = tf.concat(2, [tf.squeeze(x) for x in X])  # bsize, b, a*r, r
  X = tf.split(1, b, X)  # b, [bsize, a*r, r]
  X = tf.concat(2, [tf.squeeze(x) for x in X])  # bsize, a*r, b*r
  return tf.reshape(X, (bsize, a*r, b*r, 1))

def PS(X, r, depth):
  Xc = tf.split(3, depth, X)
  X = tf.concat(3, [_phase_shift(x, r) for x in Xc])
  return X

def int_shape(x):
  return list(map(int, x.get_shape()))

def concat_elu(x):
    """ like concatenated ReLU (http://arxiv.org/abs/1603.05201), but then with ELU """
    axis = len(x.get_shape())-1
    return tf.nn.elu(tf.concat(axis, [x, -x]))

def set_nonlinearity(name):
  if name == 'concat_elu':
    return convat_elu
  elif name == 'elu':
    return tf.nn.elu
  elif name == 'relu':
    return tf.nn.relu
  else:
    raise('nonlinearity ' + name + ' is not supported')

def nin(x, num_units, **kwargs):
    """ a network in network layer (1x1 CONV) """
    s = int_shape(x)
    x = tf.reshape(x, [np.prod(s[:-1]),s[-1]])
    x = dense(x, num_units, **kwargs)
    return tf.reshape(x, s[:-1]+[num_units])

def res_block(x, a=None, filter_size=16, nonlinearity=concat_elu, keep_p=1.0, stride=1, gated=False, name="resnet"):
  orig_x = x
  x_1 = conv_layer(nonlinearity(x), 3, stride, filter_size, name + '_conv_1')
  if a is not None
    x_1 += nin(nonlinearity(a), filter_size)
  x_1 = nonlinearity(x_1)
  if keep_p < 1.0:
    x_1 = tf.nn.dropout(x_1, keep_prob=keep_p)
  if not gated:
    x_2 = conv_layer(x_1, 3, 1, filter_size, name + '_conv_2')
  else:
    x_2 = conv_layer(x_1, 3, 1, filter_size*2, name + '_conv_2')
    x_2_1, x_2_2 = tf.split(3,2,x_2)
    x_2 = x_2_1 * tf.nn.sigmoid(x_2_2)

  if int(orig_x.get_shape()[2]) > int(x_2.get_shape()[2]):
    assert(int(orig_x.get_shape()[2]) == 2*int(x_2.get_shape()[2]), "res net block only supports stirde 2")
    orig_x = tf.nn.ave_pooling(orig_x, [1,2,2,1], [1,2,2,1], padding='SAME')

  # pad it
  out_filter = filter_size
  in_filter = int(orig_x.get_shape()[3])
  orig_x = tf.pad(
      orig_x, [[0, 0], [0, 0], [0, 0],
      [(out_filter-in_filter)//2, (out_filter-in_filter)//2]])

  return orig_x + x_2

def res_block_lstm(x, hidden_state_1=None, hidden_state_2=None, keep_p=1.0, name="resnet_lstm"):

  orig_x = x
  filter_size = orig_x.get_shape()

  with tf.variable_scope(name + "_conv_LSTM_1", initializer = tf.random_uniform_initializer(-0.01, 0.01)):
    lstm_cell_1 = BasicConvLSTMCell.BasicConvLSTMCell([int(x.get_shape()[1]),int(x.get_shape()[2])], [3,3], filter_size)
    if hidden_state_1 == None:
      batch_size = x.get_shape()[0]
      hidden_state_1 = lstm_cell_1.zero_state(batch_size, tf.float32) 

  x_1, hidden_state_1 = lstm_cell_1(x, hidden_state_1)
    
  if keep_p < 1.0:
    x_1 = tf.nn.dropout(x_1, keep_prob=keep_p)

  with tf.variable_scope(name + "_conv_LSTM_2", initializer = tf.random_uniform_initializer(-0.01, 0.01)):
    lstm_cell_2 = BasicConvLSTMCell.BasicConvLSTMCell([int(x_1.get_shape()[1]),int(x_1.get_shape()[2])], [3,3], filter_size)
    if hidden_state_2 == None:
      batch_size = x_1.get_shape()[0]
      hidden_state_2 = lstm_cell_2.zero_state(batch_size, tf.float32) 

  x_2, hidden_state_2 = lstm_cell_2(x_1, hidden_state_2)

  return orig_x + x_2, hidden_state_1, hidden_state_2


# GAN Stuff
def discriminator_32x32x1(x, hidden_state, keep_prob):
  """Builds discriminator.
  Args:
    inputs: i
  """
  #--------- Making the net -----------
  # x_2 -> hidden_state

  # split x
  num_of_d = 8
  x_split = tf.split(0,num_of_d, x)
  label = []

  for i in xrange(num_of_d):
    # conv1
    conv1 = _conv_layer(x_split[i], 5, 2, 32, "discriminator_1_" + str(i))
    # conv2
    conv2 = _conv_layer(conv1, 5, 2, 64, "discriminator_2_" + str(i))
    
    y_1 = _fc_layer(conv2, 128, "discriminator_5_" + str(i), True)
    y_1 = tf.nn.dropout(y_1, keep_prob)
      #with tf.device('/gpu:0'):
      lstm_cell = tf.nn.rnn_cell.BasicLSTMCell(128, forget_bias=1.0)
      if hidden_state == None:
        batch_size = y_1.get_shape()[0]
        hidden_state = lstm_cell.zero_state(batch_size, tf.float32)
  
      y_2, new_state = lstm_cell(y_1, hidden_state)
  
    label.append(_fc_layer(y_2, 1, "discriminator_6_" + str(i), False, True))

  label = tf.pack(label)
  
  return label, new_state

def discriminator_401x101x2(x, hidden_state, keep_prob):
  """Builds discriminator.
  Args:
    inputs: i
  """
  #--------- Making the net -----------
  # x_2 -> hidden_state

  # split x
  num_of_d = 2
  x_split = tf.split(0,num_of_d, x)
  label = []

  for i in xrange(num_of_d):
    # conv1
    conv1 = _conv_layer(x, 5, 2, 64, "discriminator_1_" + str(i))
    # conv2
    conv2 = _conv_layer(conv1, 3, 2, 128, "discriminator_2_" + str(i))
    # conv3
    conv3 = _conv_layer(conv2, 3, 2, 256, "discriminator_3_" + str(i))
    # conv4
    conv4 = _conv_layer(conv3, 3, 2, 128, "discriminator_4_" + str(i))
  
    y_1 = _fc_layer(conv4, 256, "discriminator_5_" + str(i), True)
 
    with tf.variable_scope("discriminator_LSTM_" + str(i), initializer = tf.random_uniform_initializer(-0.01, 0.01)):
      #with tf.device('/gpu:0'):
      lstm_cell = tf.nn.rnn_cell.BasicLSTMCell(256, forget_bias=1.0)
      if hidden_state == None:
        batch_size = y_1.get_shape()[0]
        hidden_state = lstm_cell.zero_state(batch_size, tf.float32)

      y_2, new_state = lstm_cell(y_1, hidden_state)

    label.append(_fc_layer(y_2, 1, "discriminator_6_" + str(i), False, True))

  label = tf.pack(label)

  return label, new_state



