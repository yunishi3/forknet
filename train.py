import numpy as np
import tensorflow as tf

from config import cfg
from util import DataProcess, scene_model_id_pair
from model import depvox_gan

from colorama import init
from termcolor import colored

init()


def learning_rate(rate, step):
    if step < rate[1]:
        lr = rate[0]
    else:
        lr = rate[2]
    return lr


def train(n_epochs, learning_rate_G, learning_rate_D, batch_size, mid_flag,
          check_num):
    beta_G = cfg.TRAIN.ADAM_BETA_G
    beta_D = cfg.TRAIN.ADAM_BETA_D
    n_vox = cfg.CONST.N_VOX
    dim = cfg.NET.DIM
    vox_shape = [n_vox[0], n_vox[1], n_vox[2], dim[4]]
    tsdf_shape = [n_vox[0], n_vox[1], n_vox[2], 3]
    dim_z = cfg.NET.DIM_Z
    start_vox_size = cfg.NET.START_VOX
    kernel = cfg.NET.KERNEL
    stride = cfg.NET.STRIDE
    dilations = cfg.NET.DILATIONS
    freq = cfg.CHECK_FREQ
    record_vox_num = cfg.RECORD_VOX_NUM
    # refine_ch = cfg.NET.REFINE_CH
    # refine_kernel = cfg.NET.REFINE_KERNEL
    # refiner = cfg.NET.REFINER
    discriminative = cfg.NET.DISCRIMINATIVE
    generative = cfg.NET.GENERATIVE
    variational = cfg.NET.VARIATIONAL

    # refine_start = cfg.SWITCHING_ITE

    depvox_gan_model = depvox_gan(
        batch_size=batch_size,
        vox_shape=vox_shape,
        tsdf_shape=tsdf_shape,
        dim_z=dim_z,
        dim=dim,
        start_vox_size=start_vox_size,
        kernel=kernel,
        stride=stride,
        dilations=dilations,
        # refine_ch=refine_ch,
        # refine_kernel=refine_kernel,
        # refiner=refiner,
        generative=generative)

    Z_tf, z_tsdf_enc_tf, z_vox_enc_tf, vox_tf, vox_gen_tf, vox_gen_decode_tf, vox_vae_decode_tf, vox_cc_decode_tf, tsdf_seg_tf,\
    gen_vae_loss_tf, gen_cc_loss_tf, gen_gen_loss_tf, code_encode_loss_tf, gen_loss_tf, discrim_loss_tf,\
    cost_enc_tf, cost_code_tf, cost_gen_tf, cost_discrim_tf, summary_tf,\
    tsdf_tf, tsdf_gen_tf, tsdf_gen_decode_tf, tsdf_vae_decode_tf, tsdf_cc_decode_tf = depvox_gan_model.build_model()
    global_step = tf.Variable(0, name='global_step', trainable=False)
    config_gpu = tf.ConfigProto()
    config_gpu.gpu_options.allow_growth = True
    sess = tf.Session(config=config_gpu)
    saver = tf.train.Saver(max_to_keep=cfg.SAVER_MAX)

    data_paths = scene_model_id_pair(dataset_portion=cfg.TRAIN.DATASET_PORTION)
    print '---amount of data:' + str(len(data_paths))
    data_process = DataProcess(data_paths, batch_size, repeat=True)

    encode_vars = filter(lambda x: x.name.startswith('encode'),
                         tf.trainable_variables())
    discrim_vars = filter(lambda x: x.name.startswith('discrim'),
                          tf.trainable_variables())
    gen_vars = filter(lambda x: x.name.startswith('gen'),
                      tf.trainable_variables())
    code_vars = filter(lambda x: x.name.startswith('cod'),
                       tf.trainable_variables())

    lr_VAE = tf.placeholder(tf.float32, shape=[])
    train_op_encode = tf.train.AdamOptimizer(
        lr_VAE, beta1=beta_D, beta2=0.9).minimize(
            cost_enc_tf, var_list=encode_vars)
    train_op_discrim = tf.train.AdamOptimizer(
        learning_rate_D, beta1=beta_D, beta2=0.9).minimize(
            cost_discrim_tf, var_list=discrim_vars, global_step=global_step)
    train_op_gen = tf.train.AdamOptimizer(
        learning_rate_G, beta1=beta_G, beta2=0.9).minimize(
            cost_gen_tf, var_list=gen_vars + encode_vars)
    train_op_code = tf.train.AdamOptimizer(
        lr_VAE, beta1=beta_G, beta2=0.9).minimize(
            cost_code_tf, var_list=code_vars)

    Z_tf_sample, vox_tf_sample = depvox_gan_model.samples_generator(
        visual_size=batch_size)

    writer = tf.summary.FileWriter(cfg.DIR.LOG_PATH, sess.graph_def)
    tf.initialize_all_variables().run(session=sess)

    if mid_flag:
        chckpt_path = cfg.DIR.CHECK_PT_PATH + str(check_num)
        saver.restore(sess, chckpt_path)
        """
        Z_var_np_sample = np.load(cfg.DIR.TRAIN_OBJ_PATH +
                                  '/sample_z.npy').astype(np.float32)
        """
        Z_var_np_sample = np.random.normal(
            size=(batch_size, start_vox_size[0], start_vox_size[1],
                  start_vox_size[2], dim_z)).astype(np.float32)
        Z_var_np_sample = Z_var_np_sample[:batch_size]
        print '---weights restored'
    else:
        Z_var_np_sample = np.random.normal(
            size=(batch_size, start_vox_size[0], start_vox_size[1],
                  start_vox_size[2], dim_z)).astype(np.float32)
        np.save(cfg.DIR.TRAIN_OBJ_PATH + '/sample_z.npy', Z_var_np_sample)

    ite = check_num * freq + 1
    cur_epochs = int(ite / int(len(data_paths) / batch_size))

    #training
    for epoch in np.arange(cur_epochs, n_epochs):
        epoch_flag = True
        while epoch_flag:
            print colored('---Iteration:%d, epoch:%d', 'blue') % (ite, epoch)
            db_inds, epoch_flag = data_process.get_next_minibatch()
            batch_voxel_train = data_process.get_voxel(db_inds)
            batch_tsdf_train = data_process.get_tsdf(db_inds)

            if cfg.TYPE_TASK is 'scene':
                # Evaluation masks
                volume_effective = np.clip(
                    np.where(batch_voxel_train > 0, 1, 0) + np.where(
                        batch_tsdf_train > 0, 1, 0), 0, 1)
                batch_voxel_train *= volume_effective
                batch_tsdf_train *= volume_effective

                # occluded region
                # batch_tsdf_train[batch_tsdf_train > 1] = 0

            lr = learning_rate(cfg.LEARNING_RATE_V, ite)

            batch_z_var = np.random.normal(
                size=(batch_size, start_vox_size[0], start_vox_size[1],
                      start_vox_size[2], dim_z)).astype(np.float32)

            # updating for the main network
            for s in np.arange(1):
                _, _, gen_loss_val, cost_gen_val, gen_vae_loss_val, gen_cc_loss_val, gen_gen_loss_val, code_encode_loss_val, cost_enc_val = sess.run(
                    [
                        train_op_encode, train_op_gen, gen_loss_tf,
                        cost_gen_tf, recons_vae_loss_tf, recons_cc_loss_tf,
                        recons_gen_loss_tf, code_encode_loss_tf, cost_enc_tf
                    ],
                    feed_dict={
                        vox_tf: batch_voxel_train,
                        tsdf_tf: batch_tsdf_train,
                        Z_tf: batch_z_var,
                        lr_VAE: lr
                    },
                )

            if discriminative:
                _, discrim_loss_val, cost_discrim_val = sess.run(
                    [train_op_discrim, discrim_loss_tf, cost_discrim_tf],
                    feed_dict={
                        Z_tf: batch_z_var,
                        vox_tf: batch_voxel_train,
                        tsdf_tf: batch_tsdf_train
                    },
                )

            if variational:
                _, cost_code_val, z_tsdf_enc_val, z_vox_enc_val = sess.run(
                    [train_op_code, cost_code_tf, z_tsdf_enc_tf, z_vox_enc_tf],
                    feed_dict={
                        Z_tf: batch_z_var,
                        vox_tf: batch_voxel_train,
                        tsdf_tf: batch_tsdf_train,
                        lr_VAE: lr
                    },
                )

            summary = sess.run(
                summary_tf,
                feed_dict={
                    Z_tf: batch_z_var,
                    vox_tf: batch_voxel_train,
                    tsdf_tf: batch_tsdf_train,
                    lr_VAE: lr
                },
            )

            print(colored('gan', 'red'))
            print 'reconstruct vae loss:', gen_vae_loss_val if (
                'gen_vae_loss_val' in locals()) else 'None'

            print ' reconstruct cc loss:', gen_cc_loss_val if (
                'gen_cc_loss_val' in locals()) else 'None'

            print(
                colored('reconstruct gen loss: ' + str(gen_gen_loss_val),
                        'green')) if (
                            'gen_gen_loss_val' in locals()) else 'None'

            print '    code encode loss:', code_encode_loss_val if (
                'code_encode_loss_val' in locals()) else 'None'

            print '            gen loss:', gen_loss_val if (
                'gen_loss_val' in locals()) else 'None'

            print '        cost_encoder:', cost_enc_val if (
                'cost_enc_val' in locals()) else 'None'

            print '      cost_generator:', cost_gen_val if (
                'cost_gen_val' in locals()) else 'None'

            print '  cost_discriminator:', cost_discrim_val if (
                'cost_discrim_val' in locals()) else 'None'

            print '           cost_code:', cost_code_val if (
                'cost_code_val' in locals()) else 'None'

            print '   avarage of tsdf_z:', np.mean(
                np.mean(z_tsdf_enc_val,
                        4)) if ('z_tsdf_enc_val' in locals()) else 'None'

            print '       std of tsdf_z:', np.mean(
                np.std(z_tsdf_enc_val,
                       4)) if ('z_tsdf_enc_val' in locals()) else 'None'

            print '    avarage of vox_z:', np.mean(np.mean(
                z_vox_enc_val, 4)) if ('z_vox_enc_val' in locals()) else 'None'

            print '        std of vox_z:', np.mean(np.std(
                z_vox_enc_val, 4)) if ('z_vox_enc_val' in locals()) else 'None'

            if np.mod(ite, freq) == 0:
                vox_models = sess.run(
                    vox_tf_sample,
                    feed_dict={Z_tf_sample: Z_var_np_sample},
                )
                vox_models_cat = np.argmax(vox_models, axis=4)
                record_vox = vox_models_cat[:record_vox_num]
                np.save(
                    cfg.DIR.TRAIN_OBJ_PATH + '/' + str(ite / freq) + '.npy',
                    record_vox)
                save_path = saver.save(
                    sess,
                    cfg.DIR.CHECK_PT_PATH + str(ite / freq),
                    global_step=None)

            # updating for the refining network

            writer.add_summary(summary, global_step=ite)

            ite += 1
